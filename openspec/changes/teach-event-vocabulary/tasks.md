## 1. Plumbing field

- [x] 1.1 `Invocation` gains `vocabulary: Path | None = None`; `render()` emits
      `"The event vocabulary is defined at {path}."` when set, ordered between the skill line and the
      proposal-path line.
- [x] 1.2 `protocol/backlog.py` gains `VOCABULARY_SPEC`, an absolute path to
      `openspec/specs/backlog-item-format/spec.md`, resolved from `__file__`; comment states it is a
      pointer to the mirror, not a second definition, and names the dev-checkout assumption as a
      limitation (see coordinator's check 1, addressed in `proposal.md` - Verification).
- [x] 1.3 `runtime/turn.py`'s single `Invocation(...)` call site passes
      `vocabulary=backlog.VOCABULARY_SPEC`.
- [x] 1.4 `workflows/turn-skill.md` left byte-for-byte unchanged; full suite (including its
      word-count test in `test_turn_cycle.py`) passes untouched — 269 tests, `ruff`/`ty` clean.

## 2. Spec

- [x] 2.1 `turn-cycle`'s "The frame is not the channel for how a run is invoked" requirement gains the
      third plumbing example and the new scenario (delta in `specs/turn-cycle/spec.md`), header text
      and both existing scenario titles kept verbatim. `openspec validate teach-event-vocabulary
      --strict` passes.

## 3. The receipt — the deferred scope of `add-take-turn-integration-receipt`

- [x] 3.1 New test `test_a_real_agent_reaches_done_once_the_vocabulary_is_reachable` in
      `tests/runtime/test_turn_integration.py`: real turn, real foreign workspace,
      `test_command=("true",)`, asserting from the subject:
      - `record.outcome is Outcome.ADVANCED` — **PASSED for real**
      - the item's `.jsonl` log ends with a `done` line carrying `effects` and `verified_by` —
        **confirmed on disk**
      - the workspace's real commit — **confirmed** (`marker in notes.txt`)
      - the run's own transcript shows a `Read` tool call whose `file_path` equals
        `str(backlog.VOCABULARY_SPEC)`, before the proposal was written — **confirmed**: this is
        coordinator check 3 (distinguish "read the spec" from "guessed right"), answered from the
        subject, not inferred from the outcome.
- [x] 3.2 Module docstring updated: replaced "Not the `done` path" with what changed, pointing at
      this change's id. The historical finding (why it was `FAILED` before) is kept legible, not
      erased (D002) — restated as "was unreachable, and now is not."
- [x] 3.3 Real spend, against budget $1.00:

      | Run | Purpose | Cost | Result |
      |---|---|---|---|
      | probe (throwaway script, `claude.run()` direct, not committed) | coordinator check 2: does `Read` reach an absolute path outside the workspace under `workspace_scoped`? | $0.276 | **Yes, observed**: `Read {"file_path": "/Users/iorlas/Workspaces/yosefactory/openspec/specs/backlog-item-format/spec.md"}` succeeded (`outcome: success`, no `permission_denials`), and the agent's proposal was a legal `done` with real `effects`/`verified_by`. |
      | `test_a_real_agent_reaches_done_once_the_vocabulary_is_reachable` (pytest, real `take_turn`) | the deferred receipt itself | $0.266 | **`Outcome.ADVANCED`**, `done` written to the item log, transcript shows the `Read` of `VOCABULARY_SPEC` before the proposal write. |
      | `test_take_turn_drives_a_real_agent_against_a_real_foreign_workspace` (existing, no `test_command` override) | verify the new `FAILED` reason claimed in the docstring, not assume it | $0.278 | **Confirmed from the ledger row's own `note`**: `"VERIFICATION FAILED: tests: pytest -q exited 5: no tests ran in 0.01s"`, `enforced_by: harness` — the gate refusing an unverifiable `done`, not the agent inventing an event. |
      | **Total** | | **$0.820** | under the $1.00 cap; one wall-hit avoided (no retries needed — every run answered its question on the first attempt) |

      `test_two_turns_share_a_byte_identical_co_author_and_independent_run_ids` was **not** re-run:
      its docstring already reads "for the same reason as the test above," which the run directly
      above confirmed, and its own property (trailer identity across two commits) is orthogonal to
      the vocabulary fix and was already established in the archived receipt. Re-running it would
      have spent real money on a fact already covered twice over, working against the same
      restraint the budget is meant to enforce.
- [x] 3.4 No run produced an invented event or an unread pointer; the "stop after one wall-hit"
      branch was not exercised.

## 4. Verify

- [x] 4.1 `ruff check src/ tests/` and `ty check src/` clean (13 pre-existing `ty` diagnostics in
      `tests/protocol/test_turn.py` are unchanged by this diff — confirmed via `git stash`/`ty check`
      before this change touched anything).
- [x] 4.2 Full non-real-spend suite passes: 269 tests, both real-spend integration files excluded.
- [x] 4.3 `openspec validate teach-event-vocabulary --strict` passes on the change.
