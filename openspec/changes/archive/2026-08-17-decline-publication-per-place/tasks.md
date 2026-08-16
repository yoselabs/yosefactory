## 1. The control

- [x] 1.1 `Places` gains `publish_queue: bool = True`, `publish_workspace: bool = True`.
- [x] 1.2 `publish()` checks each flag before calling `push_repo`; a declined place returns
      `PublishResult(repo=..., status="declined", detail="publication declined for this place")`
      without invoking `push_repo`. Workspace-before-queue ordering preserved.
- [x] 1.3 `PublishResult.status`'s inline comment updated to list `"declined"`.

## 2. Spec

- [x] 2.1 `turn-publication` gains the new requirement (pure ADDED — no existing header or scenario
      title touched). `openspec validate decline-publication-per-place --strict` passes.

## 3. Tests

- [x] 3.1 `test_a_declined_workspace_is_never_pushed` — spy on `push_repo`, `publish_workspace=False`,
      asserts `calls == [repo]` (queue only) and nothing reached the workspace remote.
- [x] 3.2 `test_declined_is_not_conflated_with_skipped_even_with_a_real_remote` — a declined workspace
      with a real, reachable `origin` still reports `declined`, proving the check runs before
      `push_repo` rather than being inferred from its result.
- [x] 3.3 `test_an_unstated_publish_choice_publishes_both_places_exactly_as_before` — default behaviour
      unchanged; all three pre-existing publish tests (`test_an_advanced_turn_publishes_workspace_before_queue`
      and friends) pass unmodified.

## 4. Verify

- [x] 4.1 `ruff check src/ tests/` and `ty check src/` clean (same 13 pre-existing `ty` diagnostics in
      `tests/protocol/test_turn.py`, unrelated to this change).
- [x] 4.2 Full non-real-spend suite: 272 passed (269 + 3 new).
- [x] 4.3 `openspec validate decline-publication-per-place --strict` passes on the change.
