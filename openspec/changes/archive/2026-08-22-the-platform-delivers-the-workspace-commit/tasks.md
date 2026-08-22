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

- [x] 6.1 Two real `take_turn` attempts against a2web. First, against `a2web-luh`
      (`a2web-qgo-primary-image`, `e778fd9`): director corrected this bead as already solved on
      `fix-reddit-archive-rescue-escalation` at `9e183e4` (verified: `git merge-base --is-ancestor`
      false) before the second attempt — the first attempt itself burned $2.5073 to
      `budget_exhausted` without reaching the gate, `workspace_commit: ""`. Second, narrowed to
      `a2web-2yd`'s untested `corpus.py` `CorpusError` guards ($2.00 ceiling): `advanced`,
      `workspace_commit: 77cae868cde04ccdb5ee59057c5a3dc61b7fbc8d`. Join, both directions, from disk:
      - a2web commit `77cae868` (branch `a2web-2yd-corpus-error-tests`) trailers:
        `Co-Authored-By: yosefactory <yosefactory@yoselabs.dev>`, `Yosefactory-Run: turn-20260822T015137Z-f9845890`
      - `ledger/runs/20260822T015137Z-turn-20260822T015137Z-f9845890.json`:
        `"workspace_commit": "77cae868cde04ccdb5ee59057c5a3dc61b7fbc8d"`
- [x] 6.2 Actual spend: $2.5073 + $0.5158 = $3.0231 of the $5.00 allowance.
- [x] 6.3 Confirmed: `git ls-remote --heads origin` on a2web shows no `a2web-2yd-corpus-error-tests`
      and no `fix-reddit-forbidden-archive-silent-miss` (the first attempt's abandoned, uncommitted
      branch, deleted before the second attempt). `main` unchanged at `6f26e89`.

## 7. Archive

- [ ] 7.1 `openspec archive the-platform-delivers-the-workspace-commit` — Article XV, not implied.
- [ ] 7.2 `git diff --stat <sha>^ <sha> -- openspec/specs/...` after archiving: deletions = 0 (every
      requirement here is ADDED, nothing MODIFIED, nothing should delete).
