# Design — wire-the-board-into-the-turn-cycle

Motivation: see [proposal.md](proposal.md). Requirements: see
`specs/turn-loop/board-wiring/spec.md` and `specs/board-projection/inbox/spec.md`.

## The constraint that shaped everything else

Dispatch, quoting [[S987]]: *"an idle wake is a billed planning turn... if reading the board for
commands can trigger a planning turn, you have made every poll cost money."* Every design choice
below is downstream of keeping that structurally false, not merely true today.

**Why it holds.** `ingest()` calls exactly one thing that touches the queue: `runtime.turn.append()`
(now also `runtime.turn.commit()` — see below), the same primitive `apply_answers()` already uses.
Neither is `take_turn`, neither starts an `Executor`. The only way a board read could reach an
executor is if the loop's own code branched on "did ingest() find something" and called
`take_turn()` in response. **It does not.** Ingestion and the decision to run a turn are wired
through the queue's git history, not through each other:

```
  board poll (own cadence)  --ingest()-->  git commit  --moves HEAD-->  EXTERNAL_EVENT wake
                                                                          (existing, unmodified)
                                                                                |
                                                                                v
                                                                          take_turn() runs
```

`EXTERNAL_EVENT` already exists (`add-turn-loop`) and already fires on *any* HEAD movement — a
human's manual push, another process, or now `ingest()`'s own commit. Routing board commands
through it rather than adding a fourth wake reason means **a board command cannot skip the wake
gate even by a future change that forgets why the gate is there** — there is no direct call site
from "board said something" to "run a turn" for such a change to introduce by accident.

**The corollary this forces:** ingestion must actually reach git, i.e. it must commit. An
uncommitted write does not move `HEAD`, so it would never surface as `EXTERNAL_EVENT` — the whole
mechanism above depends on ingest's writes being real commits, not working-tree edits nobody
notices until some later unrelated commit happens to sweep them up.

## Found while building: `ingest()` never committed (design.md's "Verified before building on it")

Checked before wiring, per S194 discipline — read the code, not the proposal's assumption that
"ingest applies to git" meant "ingest commits to git":

```python
# board/inbox.py, before this change
turn_append(item_path, backlog.ITEM, {"event": "priority_set", ...}, actor=actor)
return f"priority set to {payload['priority']!r}"
```

`runtime.turn.append()` writes the candidate file and atomically replaces the log — durable on
disk, but nothing here calls `git add`/`git commit`. Every existing `test_inbox.py` test ran
against a bare `tmp_path`, no `git init` anywhere, and passed, because nothing in the module or its
tests ever needed git to exist. That is exactly what let the gap ship silently in the archived
change: the acid test (`test_reprojection.py`) exercises `project_all()`, which never writes to
git at all (git → board only); nothing exercised `ingest()` against a real repository.

**Fixed here**, not deferred: each applier now returns `(detail, touched_path)`, and `ingest()`
commits `[touched_path, consumed_log_path]` per event, using `runtime.turn.commit()` — same
function, same trailer discipline (`Co-Authored-By: yosefactory` / `Yosefactory-Run: <run_id>`),
same explicit-pathspec safety `turn.py`'s own commits already rely on. One `run_id` per `ingest()`
call (`new_run_id()`), not per event — an ingest pass reads as one platform action in `git log`,
matching how one `take_turn` call is one action regardless of how many paths it touches.

**Test fixtures changed accordingly.** `tests/board/test_inbox.py` now `git init`s its `tmp_path`
per test (the same helper `tests/runtime/test_loop.py` already defined — reused, not
reinvented) and asserts commits landed, not just that the file content changed.

## Cadence: why board polling gets its own interval, not `WakeConfig.poll_seconds`

**Chosen:** `BoardConfig.poll_seconds`, checked inside the same wait loop `_await_wake` already
runs, but on its own elapsed-time gate — independent of `wake.poll_seconds` (the cheap local
queue/HEAD check) and of `wake.heartbeat_seconds`.

**Over:** reusing `wake.poll_seconds` for both.

**Why:** `wake.poll_seconds` defaults to 5 — cheap, because it is a local `glob()` and a `git
rev-parse`. A board poll is a network call (`gh api`) against a rate-limited external service, and
this repository's own architecture.md §7 already prices the mechanism ("Argo CD... polls every 3
minutes by default"). Coupling the two would force every deployment to choose one number for both
a free local check and a metered remote one — the dispatch's "two different frequencies" stated as
a literal requirement, not a suggestion. Default `60`: cheap enough that a command lands within a
minute, sparse enough that it is nowhere near GitHub's REST rate limits at any plausible comment
volume (architecture.md §7 already measured "~4% of the hourly content-creation budget" at
5-20 writes/day for the reply side; the read side here is even cheaper per call and adds no writes
of its own beyond the events it applies).

**Board polling never blocks the loop's other wake conditions.** It is checked once per pass
through `_await_wake`'s existing `while True` loop (which already ticks every `wake.poll_seconds`),
so the loop still wakes for a ready item or a heartbeat exactly as before — a slow or unreachable
board (network error) is not modelled as fatal here (`GitHubIssuesAdapter._api` already raises
`BoardError` on a failed `gh` call); a caller that wants the loop to tolerate a board outage rather
than crash owns that decision by not passing `board=`, or a future change adds a try/except at the
call site. **Not solved here — named, because a network dependency added to an otherwise
all-local wait loop is a real new failure mode**, and pretending otherwise would be exactly the
kind of unstated risk this corpus keeps finding.

## Projection: after every turn, plus once at start

**Chosen:** `project_all()` runs (a) once, before the loop's first turn, and (b) once after every
`take_turn()` call, whatever its outcome.

**Why after every turn regardless of outcome:** a `nothing-ready` or `failed` turn is still
information Denis benefits from seeing reflected — an item stuck `blocked` because its question
timed out, or a `claimed`-but-never-resolved item (the sweeper debt, named and not fixed here),
are exactly the states where the board *should* differ from what it showed last, and where seeing
that on his phone is the entire point of §7. `project_all()` is unconditionally cheap (no
executor, bounded by open-item count — the same O(history) caveat §10 already names and this
change does not change) so gating it on outcome would save nothing and would cost the one property
that matters: the board never silently lags a turn that actually ran.

**Why also before the first turn:** items can exist in git before the loop is ever wired to a
board — this run's own receipt is exactly that case. Skipping the initial pass would mean a fresh
`run_loop(..., board=...)` shows nothing on the board until its *own* first turn completes, even
though the queue already has real state.

## What was deliberately not added

- **No fourth `WakeReason`.** See the constraint section above — routing through `EXTERNAL_EVENT`
  is the point, not an oversight.
- **No board-side backoff/retry policy for a failed `gh` call.** Named above as a real gap, left
  for whoever wires this into the container's default compose config (`C''` in the night-run log).
- **No change to `take_turn` or `runtime/turn.py`.** The board's read (`ingest()`) and the
  reducer's read (`items()`, `apply_answers()`) remain two different functions reading the same
  git history independently — architecture.md §7's "the reducer reads git to decide, never the
  board" holds structurally: `take_turn` still never imports anything from `yosefactory.board`.

## The single-operator topology, carried forward from [[S988]]

`GitHubIssuesAdapter.list_events()` already dropped its actor guard (S988) because this program
runs one human, one loop, one GitHub identity. This change does not reintroduce a guard, an
addressed envelope, or an idempotency key beyond the `event_id` dedup `ingest()` already has —
architecture.md §7's three loop-to-loop guards remain out of scope until a second loop actually
exists, exactly as `add-board-projection-and-inbox`'s design.md already recorded. Restated here
because board wiring is the change that could tempt someone to "complete" §7 while touching this
code; the topology has not changed, so the guards it specified for a different one still should
not be added.
