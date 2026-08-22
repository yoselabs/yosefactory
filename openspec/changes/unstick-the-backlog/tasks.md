## 1. `backlog.py`: the `reclaimed` event, `failure()`, and `claims()`

- [x] 1.1 `ITEM.rules`: added `"reclaimed": Rule(frozenset({"claimed", "doing"}), "ready", required=(("reason",), ("expired_owner",), ("expired_attempt",)))`.
- [x] 1.2 New reader `failure(item: FoldedLog) -> Mapping[str, Any] | None` — `_last("failed", item)`, mirroring `falsification()`.
- [x] 1.3 New reader `claims(item: FoldedLog) -> int` — counts every `claimed` event the item's log
      has ever carried. **Not originally planned**: found while writing 3.7 below that
      `backlog.lease(target)`, the only thing `take_turn`'s claim step previously read, always
      returns `None` for a `ready` item (which `target` always is at claim time), so `attempt` could
      never exceed 1 in production. `claims()` is what makes the exhaustion cap in section 3
      reachable at all — see `design.md`.
- [x] 1.4 `openspec/specs/backlog-item-format/spec.md`'s vocabulary table gained the `reclaimed` row
      directly (not deferred to archive): `Invocation.vocabulary` points agents at this file at
      runtime and `tests/protocol/test_backlog_fold.py::test_the_vocabulary_table_promises_at_least_
      what_the_fold_requires` reads it live, so the table and `ITEM.rules` cannot be allowed to drift
      even between apply and archive. The change's own delta under `specs/backlog-item-format/`
      carries the full requirement text for archive-time promotion; this one row is the minimum
      needed for the drift guard to pass today.

## 2. `config.py`: `Guardrails.max_attempts`

- [x] 2.1 Added `max_attempts: int` to `Guardrails`, default `3` in `DEFAULTS`, validated alongside
      the other positive-int fields in `__post_init__`. Every explicit `Guardrails(...)` construction
      site across `src/` and `tests/` updated (no dataclass-level default, matching every sibling
      field) — `src/yosefactory/runtime/loop.py`, `tests/runtime/test_turn_cycle.py`,
      `tests/runtime/test_turn_integration.py`, `tests/runtime/test_loop.py`,
      `tests/executor/test_integration.py`, `tests/runtime/test_supervise.py`.

## 3. `turn.py`: the reclaim/poison sweep, committed immediately, before anything else the turn does

- [x] 3.1 `in_flight(item: FoldedLog) -> bool` — `item.state in ("claimed", "doing")`.
- [x] 3.2 `should_plan` rewritten to `not any(in_flight(item) for item in backlog_items)`.
- [x] 3.3 `_poison_if_exhausted(item_path, folded, *, actor, max_attempts) -> None` — if
      `folded.state == "failed"`, reads `backlog.failure(folded)`; appends `poisoned` when
      `retryable is False` or `attempt >= max_attempts`.
- [x] 3.4 `reclaim_expired(repo, *, actor, now, max_attempts) -> list[Path]` — for every item in
      `claimed`/`doing` whose lease's `expires_at` has passed: if `attempt >= max_attempts`, appends
      `failed` (`retryable: false`, naming the exhausted lease) then `poisoned`; else appends
      `reclaimed`. Returns every path touched.
- [x] 3.5 `apply_answers`'s return value is no longer discarded: `take_turn` collects it (mapped to
      item paths) alongside `reclaim_expired`'s return into one `swept: list[Path]`.
- [x] 3.6 **Shape changed from the original plan.** Rather than threading `extra_paths` through
      `_dispose`/`_finish` (which would only commit swept paths at the very end of the turn, after
      a possibly long executor run — during which they would sit uncommitted, exactly the defect
      being fixed), `swept` is committed immediately, in its own commit, right after the sweep runs
      and before `present = items(...)` is even read — mirroring the existing "claim commit before
      the agent runs" pattern already used for `item_path`. Simpler, and closes the same window the
      original apply_answers gap was open for.
- [x] 3.7 `_dispose` gained `max_attempts: int` (threaded from both call sites in `take_turn`) and
      calls `_poison_if_exhausted` right after the agent-authored `failed` event is appended, before
      `_finish` — landing in the same commit as that event, no extra plumbing needed.
- [x] 3.8 `take_turn`'s claim-attempt computation changed from `backlog.lease(target)` to
      `backlog.claims(target) + 1` (see 1.3) — otherwise the exhaustion cap this section adds could
      never fire.

## 4. `loop.py`: the loud exit code

- [x] 4.1 `main()`: after `run_loop(...)` returns `report`, calls `stall.detect(places.ledger)`
      (default window), prints its `.report()` line, and returns `{Status.OK: 0, Status.STALLED: 1,
      Status.STARVED: 2}[verdict.status]` instead of the previous unconditional `return 0`.
- [x] 4.2 `stall` imported at module level (moved from a planned local import inside `main()`, so
      tests can `monkeypatch.setattr(loop_mod.stall, "detect", ...)` directly).

## 5. Specs and ADR

- [x] 5.1 `openspec/specs/backlog-item-format/spec.md` delta (this change) — `reclaimed` in the
      vocabulary table, one MODIFIED scenario, one ADDED requirement with 4 scenarios.
- [x] 5.2 `openspec/specs/turn-cycle/spec.md` delta — two MODIFIED requirements (classification,
      answers-applied-before-classification, the latter widened in scope to cover the reclaim sweep
      and the commit-scoping guarantee too, full original content preserved per the strict validator's
      own check), one ADDED requirement ("Only live claims suppress planning") with 2 scenarios.
- [x] 5.3 `openspec/specs/turn-loop/wake-and-bound/spec.md` delta — one MODIFIED requirement
      correcting the now-false "snoozed backlog costs nothing" scenario.
- [x] 5.4 `openspec/specs/run-guardrails/stall-detection/spec.md` delta — one ADDED requirement, 3
      scenarios, for the CLI exit code.
- [x] 5.5 `decisions/0012-lease-reclaim-and-should-plan-narrowed-to-in-flight.md` — the three-way
      `should_plan` tradeoff, the attempt-cap reasoning, the `attempt`-could-never-exceed-1 bug, the
      commit-scoping bug, the still-alive-original-turn race, and the loud-exit-code scope line, each
      with a `Revisit trigger:`.

## 6. Tests

- [x] 6.1 `tests/protocol/test_backlog_fold.py`: `reclaimed` legal from `claimed`/`doing` only,
      illegal from `ready`, requires its three fields, folds to `ready`; `claims()` counts the whole
      history across a `released`/re-`claimed` cycle, not just the current lease.
- [x] 6.2 **The regression test S1021 asks for directly**:
      `test_a_single_failed_item_does_not_freeze_planning_forever` and
      `test_a_backlog_of_only_falsified_and_needs_split_items_still_plans` — a backlog whose only
      item(s) are stuck in a non-terminal, non-eligible state, asserting a subsequent turn plans
      instead of reporting `nothing-ready` forever.
- [x] 6.3 `test_an_expired_lease_is_reclaimed_and_may_be_reclaimed_in_the_same_turn` — an item claimed
      by a turn that never finished; the next turn reclaims it to `ready` and re-claims it in the same
      turn, `attempt` correctly at 2.
- [x] 6.4 `test_a_lease_that_keeps_expiring_is_poisoned_not_reclaimed_forever` — an item at the attempt
      ceiling on an expired lease ends `poison` via `failed`+`poisoned`, never another `reclaimed`.
- [x] 6.5 `test_a_non_retryable_failure_poisons_immediately` /
      `test_a_retryable_failure_under_the_cap_is_not_poisoned`.
- [x] 6.6 `test_a_sweeps_writes_are_committed_with_the_turn_and_do_not_dirty_the_tree` — the
      commit-scoping fix: a swept item other than the one the turn acts on is reachable from `HEAD`
      by walking its own file history, and the tree is clean (`git status --porcelain` empty) after.
      (The originally planned `TurnRecord.dirty is False` assertion was dropped: `dirty` is computed
      *before* the acted-on item's own event is committed, on every turn, by long-standing design —
      unrelated to the sweep, and not something this change changes or should assert about.)
- [x] 6.7 `test_should_plan_is_suppressed_only_by_a_live_claim` — unit coverage: `claimed`/`doing`
      suppress it; `failed`, `falsified`, `needs_split`, `blocked`, `snoozed` do not, individually and
      mixed.
- [x] 6.8 `test_a_stalled_ledger_makes_main_exit_non_zero` / `test_a_starved_ledger_exits_with_its_
      own_distinct_status` / `test_a_healthy_ledger_exits_zero_exactly_as_before` — real `TurnRecord`s
      seeded directly into `ledger/runs/`, `run_loop` faked to a no-op so `main()`'s own post-loop
      stall check is what is under test.
- [x] 6.9 Full suite: `uv run pytest -q` — 380 passed, 13 deselected (365 pre-existing + 15 new).
      `ruff check src/ tests/` and `ty check src/` clean. `make check` green end-to-end including
      `check_orchestration_citations`.

## 7. Archive

- [x] 7.1 `openspec validate unstick-the-backlog --strict` passes.
- [ ] 7.2 `openspec archive unstick-the-backlog` — Article XV, not implied.
- [ ] 7.3 `git diff --stat <sha>^ <sha> -- openspec/specs/...` after archiving: every deletion sits
      inside a block this change declared MODIFIED and named in the commit message (the corrected
      `wake-and-bound` scenario; `backlog-item-format`'s vocabulary table row was pre-added, so its
      archive diff should show no further change there beyond the new Requirement/scenarios).
