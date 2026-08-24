## Why

S238 (K project 160): `guard-transcript-ignore-with-ledger`'s fix works — measured live, twice,
today — and cannot heal the population that needs it. `ensure_transcripts_ignored()` is called from
`take_turn`. `run_loop` calls `_refuse_if_dirty(places.workspace)` once, before any iteration, at
`loop.py:331`. A `Places.local` workspace that took a turn before the guard existed carries
untracked `*.stream.jsonl` files already, so `_refuse_if_dirty` raises `LoopError` before
`take_turn` — and the guard it would have written — ever runs. Measured against `d5e5c55`: run 1
`LoopError: refusing to start`; transcripts removed by hand; run 2 wrote the exclude and completed
clean. The population the fix targets is exactly the population it refuses to start on.

## What Changes

- `run_loop` calls `ensure_transcripts_ignored(places.ledger, places.workspace)` itself, before
  `_refuse_if_dirty`, so the exclusion exists before the dirty check that would otherwise trip on
  it.
- `take_turn`'s own call stays. It is the only call site for direct callers of `take_turn`
  (`scripts/run_a2web_turn.py`, several tests) that never go through `run_loop`, and the function is
  idempotent and cheap — two call sites cost nothing and each caller stays correct on its own.
- `_refuse_if_dirty` itself is unchanged. It is correct: a dirty tree is a real race with
  `take_turn`'s own commit. The bug is ordering, not the check.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `turn-cycle`: the transcript-exclusion requirement now also covers the loop-startup path — the
  guard must be asserted before `run_loop`'s own dirty-tree refusal, not only inside `take_turn`.

## Impact

- `src/yosefactory/runtime/loop.py` — one call added in `run_loop`, before `_refuse_if_dirty`.
- Tests: `tests/runtime/test_loop.py` — a workspace with a pre-existing untracked
  `*.stream.jsonl` must start `run_loop` successfully, not raise `LoopError`; shown to fail before
  this change and pass after.
- No change to `take_turn`, `_refuse_if_dirty`, or `ensure_transcripts_ignored` themselves.

## Non-goals

- Not weakening `_refuse_if_dirty` — a genuinely dirty tree (human edits, anything other than the
  platform's own transcripts) must still refuse the loop.
- Not removing `take_turn`'s own call site — direct callers depend on it.
- Not migrating already-*tracked* transcripts (S238's caveat: two files committed in this
  repository in 2026-08-17, before any exclude rule existed) — that is a one-time `git rm --cached`
  on this repository, not a defect in the guard.
