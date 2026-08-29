## 1. `runtime/loop.py` — delete the ceiling

- [x] 1.1 Remove `LoopBound.spend_ceiling_usd` field and its `__post_init__` validation branch.
- [x] 1.2 Remove `StopReason.SPEND_CEILING`.
- [x] 1.3 Remove the `spent_so_far()` closure; inline `spend.total_since(start_moment,
      resolved_spend_log)` at the one remaining call site (`MAX_ITERATIONS` return).
- [x] 1.4 Remove the mid-loop cumulative-ceiling check block (the `if bound.spend_ceiling_usd is
      not None:` block in the `while True:` loop), including the per-turn `cost_ceiling_usd`
      derivation (S244) it carried — that derivation only existed to make the cumulative ceiling
      safe and has nothing left to attach to once it is gone.
- [x] 1.5 Remove the `--spend-ceiling-usd` argparse argument from `main()`; update `--cost-ceiling-
      usd`'s own help text (it referenced `--spend-ceiling-usd` by name).
- [x] 1.6 `LoopBound(max_iterations=args.max_iterations, ...)` construction drops the deleted
      keyword.
- [x] 1.7 Update every module/function docstring that names `spend_ceiling_usd`,
      `--spend-ceiling-usd`, `StopReason.SPEND_CEILING`, or the derivation (module docstring,
      `LoopBound`, `run_loop`, `main`, `scheduled_main`) — remove or rewrite, do not leave a stale
      reference to a deleted mechanism.
- [x] 1.8 `scheduled_main`'s docstring stops naming `--spend-ceiling-usd` as its reason to exist;
      states the three things `unattended=True` still gates (isolation policy, publish default) —
      see design.md.

## 2. `tests/runtime/test_loop.py`

- [x] 2.1 Delete the "spend ceiling" test block: `test_the_loop_stops_at_the_spend_ceiling_before_
      the_iteration_bound`, `test_a_turn_with_no_explicit_per_turn_ceiling_receives_one_derived_
      from_remaining_budget`, `test_an_explicit_per_turn_ceiling_is_never_overridden_by_the_
      derivation`, `test_the_spend_ceiling_is_ignored_when_unset`.
- [x] 2.2 Delete `test_scheduled_main_refuses_to_start_without_a_spend_ceiling` (the flag it tests
      no longer exists) and replace with `test_scheduled_main_no_longer_requires_a_spend_ceiling`:
      `scheduled_main(["--max-iterations", "1"])` reaches `run_loop` (does not raise `SystemExit`
      before it).
- [x] 2.3 Add a negative test proving the field is actually gone, not merely unused:
      `LoopBound(max_iterations=1, spend_ceiling_usd=5.0)` raises `TypeError` (unexpected keyword).
- [x] 2.4 Add a negative test: `"SPEND_CEILING" not in loop_mod.StopReason.__members__`.
- [x] 2.5 Add a negative test: `main(["--max-iterations", "1", "--spend-ceiling-usd", "1.0"])`
      (against a real repo fixture) raises `SystemExit` — argparse rejects the removed flag as
      unrecognized.
- [x] 2.6 Fix every remaining `LoopBound(...)` construction in this file that passed
      `spend_ceiling_usd` incidentally (not testing it) to drop the keyword.
- [x] 2.7 Remove the now-dead `LimitsCapturingExecutor` if nothing else in the file still uses it
      (check before deleting — do not delete a fixture another test still needs).

## 3. Verify `spend.total_since` and `LoopReport.spend_usd` are unaffected

- [x] 3.1 Confirm `src/yosefactory/runtime/spend.py` is untouched (no code change) — `total_since`
      stays, per design.md.
- [x] 3.2 Confirm `tests/conftest.py` is untouched and its `test-live` session-spend report still
      imports and calls `spend.total_since` (it does not go through `runtime.loop` at all).
- [x] 3.3 `LoopReport.spend_usd` field itself is untouched — only its computation moves from a
      named closure to an inline call (task 1.3).

## 4. ADR

- [x] 4.1 Write `decisions/00NN-delete-the-cumulative-spend-ceiling.md` (next free number after
      `0019`) — states the never-fired evidence, D034's ruling, the `scheduled_main` survival
      reasoning, and the `factory-state` breaking change explicitly.

## 5. Validate, check, archive

- [x] 5.1 `make check` green, run inside Docker (`docker run --rm -v "$PWD":/app -w /app <image>
      make check`) — never on the host.
- [x] 5.2 `openspec validate delete-the-cumulative-spend-ceiling --strict` passes.
- [x] 5.3 Commit with explicit literal pathspecs (Article V); confirm `git diff --cached` empty
      after.
- [x] 5.4 Archive the change; confirm `git diff --stat <sha>^ <sha> --
      openspec/specs/turn-loop/wake-and-bound/spec.md` shows only the declared MODIFIED
      requirement, no other deletions.
