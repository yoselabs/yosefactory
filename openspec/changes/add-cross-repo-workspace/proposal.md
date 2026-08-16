## Why

[[D014]]'s clock counts a commit to `a2web` produced through the platform, and `take_turn` has never
run against any repository but `yosefactory` itself. The reason is structural, not missing wiring:
`repo: Path` in `runtime/turn.py` is bound once and plays four distinct roles at once — the backlog
queue, the run ledger, the single-flight lock, and the agent's own workspace (cwd, test command,
`tree_clean`/`dirty` subject, commit destination). Pointing that one path at `a2web` would grow
`backlog/`, `questions/` and `ledger/` directories inside a client repository and fill its git log
with factory bookkeeping — [[architecture.md]] §7b names the executor's workspace parameter and
already keeps it distinct from `runs_dir`; the queue and the lock never received the same treatment.

This change splits the four roles apart so a turn can read its queue from one repository and write
its work into another, with the single-repo case — everything this project runs today — preserved
exactly as a special case where all four roles happen to coincide.

## What Changes

- Introduce a `Places` value (queue, ledger, queue lock, workspace, workspace lock) that `take_turn`
  reads instead of one `repo: Path`. `Places.local(repo)` derives all five from one path exactly as
  `ITEMS`/`QUESTIONS`/`RUNS`/`LOCK` do today, so every existing call site and test is unaffected.
- Split the single-flight lock into two, because it was already doing two jobs that one repository
  made look like one: a **queue lock** serializing pick-and-claim against one backlog, and a
  **workspace lock** serializing agent execution and commits against one working tree, keyed by the
  workspace's own identity rather than by which queue dispatched the turn. Two different queues
  (loops) pointed at the same workspace now correctly serialize against each other; a queue-scoped
  lock alone cannot see that collision.
- Restate `run-guardrails/run-supervision`'s overlap guarantee against the workspace the run will
  execute in, not against an implicit "the tree" that assumed queue and workspace were the same
  repository.
- Record, without prescribing a mechanism, that a cross-repo turn's atomicity gap is a **duplicate
  risk, not a lost record**: a turn killed between the workspace commit and the queue's `done` write
  leaves the item non-terminal (lease expires, item returns to `ready`) while the workspace commit
  already exists — a retry may re-attempt a goal already landed, but the queue's own record of what
  it knows is never false. This generalizes a window that already exists single-repo, between the
  agent's own commit and the queue's terminal record — the split makes the two sides visibly
  different repositories, it does not create the hazard. Architecture.md §11 currently states this
  more strongly ("permanently disagreeing") than is warranted and should be corrected there, not here.
- **Explicitly out of scope**: naming the flag or config shape that admits a workspace repository's
  own `CLAUDE.md`/skills while still excluding the operator's host configuration. [[S190]] measured
  that the isolation flags believed to be selective were not, and the only verified control was the
  all-or-nothing safe-mode combination. Proposing a shape before a receipt confirms the binary can
  do this separably would repeat exactly the mistake `isolation-invocation`'s verified-from-the-
  stream rule exists to prevent. A separate change, gated on a measurement against an `a2web`-shaped
  fixture, owns this.

## Capabilities

### New Capabilities
- `turn-places`: the four-role split itself — what `Places` is, what `Places.local` preserves, and
  the workspace-identity keying of the second lock.

### Modified Capabilities
- `turn-cycle`: "A turn is a function of repository state" and "Concurrency is safe on one machine
  and fails loudly across machines" both currently assume one repository plays every role; both need
  restating against queue and workspace as potentially distinct.
- `run-guardrails/run-supervision`: "Runs do not overlap on the same working tree" needs its lock
  scope stated against the workspace identity, not against an implicit single repository.

## Impact

- `src/yosefactory/runtime/turn.py` — `take_turn`'s signature and every internal reference to `repo`.
  **Contended**: YF-6 is applying `write-the-reason-fields` here now; YF-5's trailer change against
  `turn.commit()` follows. This proposal does not touch `turn.commit()`'s trailer behaviour, which
  already works unchanged under the split, per the director's instruction.
- `src/yosefactory/runtime/supervise.py` — `single_flight`'s call sites gain a second, workspace-
  keyed invocation; `tree_is_dirty` already takes a `repo` parameter compatible with either role.
- `src/yosefactory/runtime/verify.py` — `may_write_done`'s `repo` parameter must resolve to the
  workspace, not the queue, once they diverge.
- Tests under `tests/runtime/` and `tests/executor/test_integration.py` exercise the single-repo
  collapse and are expected to pass unchanged against `Places.local`.
