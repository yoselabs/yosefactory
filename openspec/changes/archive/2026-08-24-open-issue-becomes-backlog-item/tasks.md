## 1. Event vocabulary

- [x] 1.1 `board/event.py::TYPES` gains `"create"`. `parse_command()` unchanged — `create` is
      never parsed from comment text.

## 2. GitHub adapter

- [x] 2.1 `board/github.py::list_events()`: an issue whose body carries no `yosefactory:item=`
      marker emits a `create` `Event` (title/body read fresh, not cached) instead of being skipped.
      `event_id` derived from the issue number so it is stable across polls of the same
      not-yet-ingested issue.
- [x] 2.2 Comment scanning is skipped for a markerless issue this pass (design.md, "no
      comment-scanning on a markerless issue").

## 3. Ingest

- [x] 3.1 `board/inbox.py`: new `_apply_create(repo, payload, *, actor) -> (item_id, detail,
      touched_path)` — builds the degenerate frame (goal=title, method=body or placeholder,
      assumptions=fixed literal), allocates `turn.new_item_id()`, appends `created` with
      `loop="board-intake"`.
- [x] 3.2 `ingest()` branches on `event.type == "create"` ahead of the `_APPLIERS` dispatch
      (design.md, "why `create` is not in `_APPLIERS`"): on success, calls
      `adapter.project(item, ref)` on the source thread before recording/committing; on failure,
      records/comments a rejection exactly like the other three, with no item log left behind.

## 4. Tests

- [x] 4.1 `tests/board/test_inbox.py`: a `create` event produces a new item with the expected
      degenerate frame, `state == "ready"`, `loop == "board-intake"`.
- [x] 4.2 `tests/board/test_inbox.py`: an empty-body `create` still produces a legal frame (no
      `LogError` from `backlog.ITEM`'s required fields).
- [x] 4.3 `tests/board/test_inbox.py`: `adapter.project(item, ref)` is called with the new item and
      the originating `ref` after a successful create (asserted against `FakeAdapter`).
- [x] 4.4 `tests/board/test_inbox.py`: a `create` whose `created` append is refused (e.g. the fold
      rejects it) is recorded as `rejected`, commented on the thread, and leaves no item file
      behind — mirrors the existing rejection tests for the other three verbs.
- [x] 4.5 New test module exercising `GitHubIssuesAdapter` directly against a **fake `gh` transport
      the test owns** (no real `gh`, no network — see design.md and the closing report for what
      this does and does not prove): an issue with no marker yields a `create` event from
      `list_events()`; after `project()` writes the marker back, a second `list_events()` call
      against the same (now-updated) fake state no longer offers it — the structural,
      write-then-reread proof for the double-ingest prevention this change claims. A test that
      fails before this change's code exists (or with the old skip-if-no-marker behavior restored)
      and passes after.

## 5. Spec, ADR, and archive

- [x] 5.1 `openspec validate open-issue-becomes-backlog-item --strict` passes.
- [x] 5.2 `decisions/0016-*.md`: the thin-issue frame choice and the marker-write-back-as-
      idempotence mechanism, each with a `Revisit trigger:` line.
- [x] 5.3 `make check` passes.
- [x] 5.4 Archive; confirm `git diff --stat <sha>^ <sha> -- openspec/specs/...` shows only
      additions inside the `board-projection/inbox` block declared MODIFIED above, plus the new
      ADDED requirement.
- [x] 5.5 Re-run `make check` after archiving.
- [x] 5.6 Report back to the director for write-back against D031/D028/D029: what a thin issue does
      and why, how double-ingest is prevented and how that was tested, and the open question named
      in design.md (no concurrent-`ingest()` lock).
