## 1. Guard

- [x] 1.1 In `run_loop` (`loop.py`), call `runs.ensure_transcripts_ignored(places.ledger,
      places.workspace)` immediately before `_refuse_if_dirty(places.workspace)`.
- [x] 1.2 Leave `take_turn`'s own call site unchanged.

## 2. Tests

- [x] 2.1 Regression test in `tests/runtime/test_loop.py`: a `Places.local` workspace with a
      pre-existing untracked `*.stream.jsonl` file starts `run_loop` successfully (no
      `LoopError`) — confirmed to fail before this change and pass after.

## 3. Verify

- [x] 3.1 `make check` green.
- [ ] 3.2 Re-run `make check` after archiving.
