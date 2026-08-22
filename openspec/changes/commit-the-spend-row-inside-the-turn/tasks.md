## 1. Move recording from the executor to the turn

- [x] 1.1 `src/yosefactory/runtime/turn.py`: new `spend_log_for(places: Places) -> Path`, returning
      `places.ledger.parent / "spend.jsonl"`.
- [x] 1.2 `_dispose`: every `_finish(...)` call site (`failed`, `blocked`, planning return, normal
      return) threads `total_cost_usd=result.usage.total_cost_usd`.
- [x] 1.3 `_finish`: gains `total_cost_usd: float | None = None`. Computes `dirty` first, writes the
      spend row second (wrapped, `OSError` folds into `note` rather than propagating), builds the
      `TurnRecord`, then commits `[*paths, written, written.with_suffix(".start"), spend_log]` in
      one `commit()` call.
- [x] 1.4 `src/yosefactory/executor/claude.py`: remove the `spend.record()` call and the now-unused
      `runtime.spend` import.

## 2. Resolve the spend log from `Places`, not the package location

- [x] 2.1 `src/yosefactory/runtime/loop.py::run_loop`: `spend_log` becomes `Path | None = None`,
      resolved internally to `spend_log_for(places)` when not given. `spent_so_far()` reads the
      resolved value.
- [x] 2.2 `src/yosefactory/runtime/spend.py`: docstring states `SPEND_LOG`'s retained scope (no
      `Places` in view) and points real turns at `spend_log_for`. `SPEND_LOG` itself is unchanged.

## 3. Spec and ADR

- [x] 3.1 `openspec/specs/turn-cycle/spec.md` delta (this change) — one ADDED requirement, 5
      scenarios: nonzero cost committed, zero cost still committed, no executor means no row, a
      write failure doesn't cost the run record, and the row lands in the repo `commit()` can
      stage.
- [x] 3.2 `decisions/0011-spend-row-committed-by-the-turn-not-the-executor.md` — the sequencing and
      `SPEND_LOG`-resolution decision, with `Revisit trigger:`.

## 4. Tests

- [x] 4.1 `tests/runtime/test_turn_cycle.py::FakeExecutor` gains `total_cost_usd: float = 0.0`.
- [x] 4.2 `test_a_turns_spend_row_is_committed_not_merely_written` — the commit-time receipt: reads
      the row back via `git show HEAD:ledger/spend.jsonl`, and confirms `ledger/spend.jsonl` is in
      the *same* commit's changed-files list as `ledger/runs/...` (not a later, separate commit).
- [x] 4.3 `test_a_turn_that_spent_exactly_zero_still_commits_a_row`.
- [x] 4.4 `test_a_planning_turn_that_created_nothing_still_commits_its_spend_row`.
- [x] 4.5 `test_a_spend_write_failure_does_not_cost_the_turn_its_run_record` — monkeypatches
      `turn.spend.record` to raise `OSError`; asserts the run record still commits, `note` names
      the failure, and no `ledger/spend.jsonl` diff appears in that commit.
- [x] 4.6 Full suite (`uv run pytest -q`): 365 passed (361 pre-existing + 4 new), 13 deselected
      (`live`-marked). `ruff check src/ tests/` and `ty check src/` clean. `make check` green
      end-to-end including `check_orchestration_citations`.

## 5. Archive

- [x] 5.1 `openspec validate commit-the-spend-row-inside-the-turn --strict` passes.
- [ ] 5.2 `openspec archive commit-the-spend-row-inside-the-turn` — Article XV, not implied.
- [ ] 5.3 `git diff --stat <sha>^ <sha> -- openspec/specs/...` after archiving: deletions = 0 (the
      only spec change here is ADDED).
