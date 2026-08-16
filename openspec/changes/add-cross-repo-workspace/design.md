## Context

See proposal.md - Why. This document covers how `Places` and the two-lock split are shaped, not why
the split is needed.

`take_turn(repo, ...)` in `runtime/turn.py` currently binds one `Path` to four uses: `repo / ITEMS`
and `repo / QUESTIONS` (queue), `repo / RUNS` (ledger), `repo / LOCK` (single-flight lock), and `repo`
itself passed through unchanged as the executor's `workspace` (agent cwd; `verify.tree_clean`,
`supervise.tree_is_dirty`, `verify.tests_pass` all take that same value; every `commit()` call in
`turn.py` targets it). `runtime/turn.py` is contended: YF-6 is applying `write-the-reason-fields` in
it now, and YF-5's trailer change against `turn.commit()` follows. This design does not touch
`turn.commit()`'s trailer mechanism.

## Goals / Non-Goals

**Goals:**
- Separate the four roles into independently named locations, with a zero-behaviour-change collapse
  back to one repository.
- Separate the single lock into a queue-scoped lock and a workspace-identity-keyed lock.
- State the atomicity property the split preserves (duplicate-risk, not silent disagreement) without
  inventing a two-phase-commit mechanism that nothing here can actually provide.

**Non-Goals:**
- The isolation flag/config shape that would admit a workspace repository's own configuration while
  excluding the operator's host configuration (proposal.md - What Changes). This needs a measurement
  this change does not run.
- A push mechanism for workspace-side commits. Nothing in the current single-repo design pushes
  either; the split makes the absence visible rather than introducing it. Flagged for whoever owns
  D014's measurement, not solved here.
- Changing `turn.commit()`'s commit-trailer behaviour, which already works unchanged under this split
  per the director's explicit instruction not to move it.
- Cross-machine coordination (compare-and-swap push) — unaffected by this change, already gated
  behind `cross_machine`/`cas_push` and refused otherwise.

## Decisions

### `Places` as a frozen dataclass with a single-repo constructor

```python
@dataclass(frozen=True, slots=True)
class Places:
    queue: Path
    ledger: Path
    queue_lock: Path
    workspace: Path
    workspace_lock: Path

    @classmethod
    def local(cls, repo: Path) -> "Places":
        return cls(
            queue=repo,
            ledger=repo / "ledger" / "runs",
            queue_lock=repo / ".git" / "yosefactory-turn.lock",
            workspace=repo,
            workspace_lock=repo / ".git" / "yosefactory-turn.lock",
        )
```

`Places.local` reproduces exactly `ITEMS`/`QUESTIONS`/`RUNS`/`LOCK`'s current derivation from `repo`,
including pointing `queue_lock` and `workspace_lock` at the *same* file when queue and workspace
coincide — `fcntl.flock` on one file taken twice by one process (queue-lock then workspace-lock, both
resolving to the same path within one turn) must not deadlock. `single_flight` opens a fresh file
handle and takes `LOCK_EX | LOCK_NB` per call; re-entering with a second handle on the same file
from the same process is a real risk to check against the actual `fcntl` semantics before wiring this
up — noted here as an implementation hazard rather than resolved, since resolving it means either
(a) `single_flight` becoming reentrant-aware within one process, or (b) `take_turn` acquiring the
lock once when `queue_lock == workspace_lock` and twice otherwise. (b) is simpler and is the
direction to build first; verify (a) is unnecessary before ruling it out.

**Alternative considered**: five separate constructor arguments to `take_turn` instead of one
`Places` value. Rejected — the four-role coupling was the defect being corrected; passing five loose
paths would let call sites recreate the same coupling by accident (e.g., a caller that means to set
`workspace` and forgets `workspace_lock` silently gets the queue's lock instead). A single value
that must be constructed explicitly, with `Places.local` as the only zero-thought path, keeps the
default safe and a deliberate split visibly deliberate.

### Two locks, not a lock hierarchy

The queue lock is held for pick-and-claim only — the same short critical section `take_turn` already
uses before invoking the executor. The workspace lock is held around the executor call, the
verification gate, and any workspace-touching commit — the same span `single_flight` already covers
today, just re-scoped to `workspace_lock` instead of the turn's single lock.

**Why keyed by workspace path, not by a workspace name or id**: the workspace *is* the resource being
protected (a working tree), and its path is already the thing every other workspace-touching
operation (`cwd=`, `tree_clean`, commits) addresses it by. Introducing a separate identifier would be
one more thing that could drift from the path it is supposed to name.

**Alternative considered**: one lock, acquired at the workspace path only, dropping the queue lock
entirely. Rejected — the queue lock protects a different resource (which item gets claimed) that two
turns against the *same* queue but *different* workspaces still need to serialize on; collapsing to
one lock would let two turns both pick the same item because neither held the queue lock while
picking.

### The atomicity statement is a detectability claim, not a prevention claim

No mechanism proposed here prevents the crash window between a workspace commit and the queue's
`done` write. What the spec commits to is narrower and already true today: the queue never writes
`done` without the verification gate passing first (`may_write_done` runs before `append(...,
"done")` in `_dispose`), so a crash in that window leaves the queue in a state that says "unknown,
retry" rather than a state that says "succeeded" falsely. Making this cross-repository does not
weaken it — the ordering constraint that produces it lives entirely in the queue-writing code, which
does not change.

The cross-reference that lets a later reader notice the workspace already holds the work — the
run-id-carrying commit trailer — is out of scope here (already being built, per the director, by
YF-5 against `turn.commit()`) and this design deliberately does not restate or move it.

## Risks / Trade-offs

- **Lock re-entrancy** (above) is unresolved and must be checked against real `fcntl` behaviour
  before `Places.local`'s single-file collapse is trusted not to deadlock a single-repo turn.
  Mitigation: acquire once when `queue_lock == workspace_lock`, as a path-equality check, rather than
  relying on `fcntl` reentrancy.
- **No push mechanism** means a workspace-side commit is not yet visible to anything outside the
  machine that made it. This change does not resolve it and states so explicitly (proposal.md).
- **Isolation posture is unresolved** for a workspace whose own configuration should load. Running a
  cross-repo turn against a real repository before that measurement lands means running with the
  current all-or-nothing isolation, which is safe (excludes everything) but likely unhelpful (also
  excludes the workspace's own conventions the agent needs). Not a correctness risk; a capability gap.
