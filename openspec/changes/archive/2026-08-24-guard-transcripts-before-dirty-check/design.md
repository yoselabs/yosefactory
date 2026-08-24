## Context

`run_loop` (`loop.py:287`) and `take_turn` (`turn.py:637`) are both real, independent entry
points — `run_loop` self-chains `take_turn`, but `scripts/run_a2web_turn.py` and several tests call
`take_turn` directly, never through the loop. `_refuse_if_dirty(places.workspace)` runs once, at
the top of `run_loop`, before the first iteration (`loop.py:331`). `ensure_transcripts_ignored`
runs inside `take_turn`, before `runs.open_run` (`turn.py:681`). Under `Places.local`, the ledger
nests inside the workspace, so an untracked `*.stream.jsonl` from a turn that ran before the guard
existed makes the workspace dirty by the same mechanism S237 fixed — and `_refuse_if_dirty` sees
that dirt before `take_turn` gets a chance to clean it.

## Goals / Non-Goals

**Goals:**
- A `Places.local` workspace carrying pre-existing untracked transcripts starts `run_loop`
  successfully instead of raising `LoopError`.
- `take_turn` stays correct when called directly, without going through `run_loop`.
- `_refuse_if_dirty` keeps refusing on any dirt that is not the platform's own transcripts.

**Non-Goals:**
- Changing what `_refuse_if_dirty` treats as dirty.
- A migration tool for already-tracked transcript files (this repo's own 2026-08-17 artifact —
  handled by hand, once, not by this change).

## Decisions

**Decision: call `ensure_transcripts_ignored` from `run_loop`, and keep `take_turn`'s call too.**

The alternative — move the call out of `take_turn` entirely, into `run_loop` only — was rejected:
`take_turn` is called directly by `scripts/run_a2web_turn.py` and by several tests
(`tests/runtime/test_turn_cycle.py`, `tests/runtime/test_turn_integration.py`) that never go
through `run_loop`. Removing the guard from `take_turn` would leave every direct caller exposed to
exactly S238's defect, just one layer down. `ensure_transcripts_ignored` is idempotent (checks the
existing `.git/info/exclude` contents before appending) and cheap (one file read, at most one
append), so calling it twice per loop-driven turn — once in `run_loop` before the dirty check, once
inside `take_turn` itself — costs a no-op on the second call and nothing else. Two call sites is the
correct shape for two independent entry points, not redundancy to be cleaned up.

**Decision: `run_loop` calls the guard, not a change to `_refuse_if_dirty`.**

`_refuse_if_dirty` was considered as the fix site — e.g. having it call the guard itself before
checking. Rejected: `_refuse_if_dirty` is a generic "is this tree dirty" check with one reason
(S184, a bind-mounted dev container racing a human editor) that has nothing to do with transcripts.
Teaching it about `ensure_transcripts_ignored` would couple a generic guard to one specific source
of dirt. `run_loop` is the caller that knows both the guard and the check exist and in what order it
needs them; ordering the two calls at the call site keeps each function's own responsibility
unchanged.

**Placement: immediately before `_refuse_if_dirty(places.workspace)`, at the top of `run_loop`.**
Earlier than the first point the workspace's own dirt is inspected, so there is no window where the
guard could still be missing when the check runs.

## Risks / Trade-offs

- **Read this design does not prove**: that a real `claude-agent-sdk` executor round-trip through
  `run_loop` (not `take_turn` directly) against a workspace with pre-existing untracked transcripts
  behaves identically to the regression test's `FakeExecutor`. The regression test drives
  `run_loop` with a fake executor and a hand-planted stale transcript file; it does not invoke the
  real `claude` binary. This mirrors the same gap the parent change (`guard-transcript-ignore-with-
  ledger`) already declared and did not close.
- **Already-tracked transcripts are out of scope.** If a workspace has `*.stream.jsonl` files
  committed into git history (not just untracked), no exclude rule un-tracks them — the guard only
  prevents *new* untracked files from counting as dirt. S238's own workspace needed a manual
  `git rm --cached` for two such files; this change does not automate that.
