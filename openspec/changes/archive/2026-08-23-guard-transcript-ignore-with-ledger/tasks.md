## 1. Guard

- [x] 1.1 Add `runs.ensure_transcripts_ignored(runs_dir, workspace)` — writes
      `/<runs_dir-relative-to-workspace>/*.stream.jsonl` into `workspace/.git/info/exclude`, no-op
      when `runs_dir` is not nested under `workspace` or `workspace` has no `.git`, idempotent.
- [x] 1.2 Call it from `take_turn`, before `runs.open_run`, so the guard exists before any
      transcript can be written this turn.

## 2. Tests

- [x] 2.1 Unit tests in `tests/runtime/test_runs.py`: guard excludes `*.stream.jsonl`, still lets
      `.start` files through, is idempotent, no-ops when ledger is outside the workspace, no-ops
      outside a git worktree.
- [x] 2.2 Regression test in `tests/runtime/test_turn_cycle.py` exercising `Places.local`
      end-to-end via `take_turn` with an executor that writes a real transcript file mid-turn —
      confirmed to fail before this change (`git status --porcelain` non-empty) and pass after.

## 3. Verify

- [x] 3.1 `make check` green.
- [x] 3.2 Re-run `make check` after archiving.
