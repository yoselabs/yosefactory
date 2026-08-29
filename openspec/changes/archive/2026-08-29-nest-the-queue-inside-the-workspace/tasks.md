## 1. `Places.nested`

- [x] 1.1 Add `Places.nested(workspace, *, queue_subdir=".factory")` in `runtime/turn.py`, alongside
      `Places.local` — see design.md for the exact shape (`queue_lock == workspace_lock`, both keyed
      off `workspace`).
- [x] 1.2 Unit test: `Places.nested(tmp_path)` produces `queue == workspace / ".factory"`,
      `ledger == queue / RUNS`, and `queue_lock == workspace_lock == workspace / LOCK`.

## 2. `_places_for` nested detection

- [x] 2.1 In `runtime/loop.py`, detect when the resolved `--queue` path is inside the resolved
      `--workspace` path and key both locks off the workspace in that case (matching
      `Places.nested`'s rule), instead of computing `queue_lock` under the queue subdirectory.
- [x] 2.2 Unit test: `_places_for(repo, queue=<workspace>/.factory, workspace=<workspace>)` returns
      `queue_lock == workspace_lock`.
- [x] 2.3 Confirm the existing fully-separate-repositories case (`--queue`/`--workspace` pointing at
      two unrelated repos) is unaffected — existing tests must still pass unmodified.

## 3. End-to-end receipt

- [x] 3.1 Write a test that fails before this change and passes after: build a real temp git
      repository as the workspace, seed one `ready` item under
      `<workspace>/.factory/backlog/items/*.jsonl` via `Places.nested`, run `take_turn` against it
      with a stub executor, and assert the item is claimed, worked, and its `done`/outcome event
      lands committed in the workspace's own git history at `.factory/backlog/items/<id>.jsonl`.
- [x] 3.2 In the same test (or a sibling one), assert the spend row for that turn is committed inside
      `<workspace>/.factory/ledger/spend.jsonl` — not anywhere outside the workspace's repository —
      confirming D033's Trail amendment ("spend follows the work") holds under nesting specifically,
      not only under `Places.local`.
- [x] 3.3 State in the test's own docstring or the closing report what this receipt does and does not
      prove (mechanics under a synthetic repo; not a real foreign workspace, not concurrency, not
      `factory-state` wiring).

## 4. Validate and archive

- [x] 4.1 `make check` passes.
- [x] 4.2 `openspec validate nest-the-queue-inside-the-workspace --strict` passes.
- [ ] 4.3 Commit with explicit pathspecs (Article V), confirm `git diff --cached` empty after.
- [ ] 4.4 Archive the change; re-run `make check` after archiving.
