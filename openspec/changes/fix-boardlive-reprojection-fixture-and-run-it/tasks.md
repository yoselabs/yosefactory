## 1. Diagnose

- [x] 1.1 Run `uv run pytest -q -m boardlive tests/board/` at HEAD, capture the verbatim failure.
- [x] 1.2 Trace the failing call to `ingest()` -> `turn_commit()` -> `git add` inside `repo`, and
      confirm `test_reprojection.py`'s `repo` fixture never creates a git repository, unlike
      `test_inbox.py`'s.
- [x] 1.3 Confirm this is a fixture defect, not a product defect, against
      `board-projection/inbox`'s existing commit requirement.

## 2. Fix

- [x] 2.1 `test_reprojection.py`'s `repo` fixture: create the directory, `git init -q`, set a
      throwaway local identity, seed one commit — same shape as `test_inbox.py`'s.
- [x] 2.2 Re-run `uv run pytest -q -m boardlive tests/board/` against real `BOARD_REPO`; both
      tests pass.

## 3. Make it runnable

- [x] 3.1 Add `make test-boardlive` to `Makefile`, mirroring `test-live`'s shape and comment
      style.
- [x] 3.2 Document `make test-boardlive` as a required step before merging/releasing a change
      that touches `src/yosefactory/board/` (`CLAUDE.md`).

## 4. Spec

- [x] 4.1 `board-projection/inbox` spec delta: ADDED requirement that the live receipt is runnable
      via a dedicated make target outside `make check`.

## 5. Verify

- [x] 5.1 `make check` green.
- [x] 5.2 `uv run pytest -q -m boardlive tests/board/` green, verbatim result captured.
- [x] 5.3 `openspec validate fix-boardlive-reprojection-fixture-and-run-it --strict` passes.
- [x] 5.4 Re-run `make check` after archiving.
