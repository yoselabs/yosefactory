## Why

[[D014]] counts a commit *produced through the platform*, and every commit the platform has ever
produced — queue-side and, as of `turn-places`, workspace-side — exists only in a local working
copy. Denis cannot see it, a receipt-reader cannot see it, and a measurement that terminates where
only the machine that ran it can see is not a measurement. [[D022]] grants the platform push,
narrowly: the current branch to `origin`, on both repositories a turn touches, after its own commits
land. This proposal builds that grant.

## What Changes

- Add a `publish` step that pushes the current branch to `origin` — no force, no tags, no branch
  creation or deletion, no remote other than one already configured — for both `places.workspace` and
  `places.queue`, workspace first (design.md - Decisions).
- Publish runs only when a turn's outcome is `advanced`. A turn that did not reach that outcome
  publishes nothing, deterministically — not by caller discipline.
- Publish runs strictly after `_finish`'s own commit lands, never inside the turn's own commit
  sequence: a publish failure cannot roll back, retry, or otherwise affect a turn that has already
  correctly recorded what happened.
- A push rejection (non-fast-forward, no remote configured, detached HEAD, network failure) is
  reported once and not retried automatically — a rejection means the remote moved or is unreachable,
  and retrying blind into a moved remote is how work gets lost.

## Capabilities

### New Capabilities
- `turn-publication`: what gets pushed, in what order, under what outcome gate, and what a rejection
  looks like.

### Modified Capabilities
(none — `take_turn`'s existing contract, one record per turn, is unchanged; publication is layered
after it, not folded into it)

## Impact

- `src/yosefactory/runtime/turn.py` — a new `publish` (or equivalently named) function and a call
  site at the end of `take_turn`, after `_finish` returns.
- Tests need a fixture supplying a local bare repository as `origin` for both queue and workspace, so
  push can be exercised without any network dependency.
