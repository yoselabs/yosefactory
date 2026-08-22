## 1. Capture the boundary

- [x] 1.1 `src/yosefactory/runtime/turn.py`: read `git rev-parse HEAD` in the workspace, once, inside
      `_workspace_lock`, before the executor runs on the item (non-planning) path only. Thread it
      into `_dispose` as `workspace_head_before: str | None`.

## 2. Deliver

- [x] 2.1 `src/yosefactory/runtime/turn.py`: new `_deliver_workspace(repo, run_id, head_before) -> str`.
      Reads `HEAD` after the gate passes; if unchanged from `head_before`, returns `""` and does
      nothing. If changed, reads the commit's message, composes trailers via the existing
      `_with_platform_trailers` (already generic on `repo`), and amends `HEAD` with
      `git commit --amend --no-verify -F <message-file>`. Returns the new SHA, or raises `TurnError`
      on refusal — never falls back to leaving the commit unmarked (mirrors `_with_platform_trailers`'s
      own no-fallback rule).
- [x] 2.2 Call it from `_dispose`'s `done` branch, only after `gate.passed`, before the item's
      `append()`. Thread the resulting SHA through to `_finish` as `workspace_commit`.

## 3. Record

- [x] 3.1 `src/yosefactory/protocol/turn.py`: `TurnRecord` gains `workspace_commit: str = ""`,
      included in `to_dict()`. No validation beyond what every other string field gets — no
      home-rooted-path check (a SHA cannot contain one), matching `model`/`effort`'s precedent.
- [x] 3.2 `src/yosefactory/runtime/turn.py`: `_finish` gains `workspace_commit: str = ""`, passed
      into `TurnRecord(...)`.

## 4. Spec

- [x] 4.1 `openspec/specs/commit-attribution/spec.md` delta (already drafted in this change) —
      4 ADDED requirements: amend-not-new-commit, never-invented, the join is bidirectional,
      hooks skipped on the amend. `openspec validate the-platform-delivers-the-workspace-commit
      --strict` passes.

## 5. Tests — $0

- [x] 5.1 `tests/runtime/test_turn.py` (or wherever `commit()`/`_with_platform_trailers` is already
      tested): a real git repo fixture; a fake executor that makes a commit in the workspace, then
      proposes `done`; assert the resulting `HEAD` commit carries both trailers, its subject/body
      are byte-identical to what the fake executor wrote, and `TurnRecord.workspace_commit` matches
      `HEAD`.
- [x] 5.2 Same fixture, executor makes **two** commits before proposing `done`: assert only the
      second (boundary) commit is amended; the first keeps its original SHA and message.
- [x] 5.3 Executor proposes `done` with **no** workspace commit (HEAD unchanged): assert no commit is
      created/amended and `TurnRecord.workspace_commit == ""`.
- [x] 5.4 A workspace with a `pre-commit`/`commit-msg` hook installed that would reject a second
      invocation (e.g. exits nonzero unconditionally): assert delivery still succeeds — proves
      `--no-verify` is actually taking effect, not merely a flag nobody exercises.
- [x] 5.5 `ruff check src/ tests/` and `ty check src/` clean.
- [x] 5.6 Full non-`live` suite passes. Confirm via `ledger/spend.jsonl` row count before/after —
      unchanged — as the $0 proof, not the test runner's exit status.

## 6. The live receipt — standing allowance $5

- [ ] 6.1 One real `take_turn` against a2web (`a2web-qgo-primary-image`, `e778fd9`), budgeted to
      $2.00 per the recent-turn precedent. After it completes:
      - `git log -1 --format='%H %B' <workspace-HEAD>` in a2web, showing both trailers on the actual
        delivered commit.
      - The turn's record from the ledger, showing `workspace_commit` equal to that same SHA.
      - Quote both directions of the join in the closing report, from disk, not from the code that
        produced them.
- [ ] 6.2 Record actual spend against the $5 allowance.
- [ ] 6.3 Confirm no push happened to either repository (`git log origin/<branch>..<branch>` on both,
      or equivalent) — this change does not touch `publish()` and must not accidentally rely on it.

## 7. Archive

- [ ] 7.1 `openspec archive the-platform-delivers-the-workspace-commit` — Article XV, not implied.
- [ ] 7.2 `git diff --stat <sha>^ <sha> -- openspec/specs/...` after archiving: deletions = 0 (every
      requirement here is ADDED, nothing MODIFIED, nothing should delete).
