## 1. Regression test (fails before, passes after)

- [x] 1.1 In `tests/runtime/test_loop.py`, a test with `LoopBound(spend_ceiling_usd=...)` set, prior
      spend recorded in the spend log, `limits.cost_ceiling_usd=None`, and a fake executor that
      captures the `Guardrails` it is invoked with — asserts the captured `cost_ceiling_usd` equals
      the remaining cumulative budget, not `None`.

## 2. Derive the per-turn ceiling

- [x] 2.1 In `run_loop` (`loop.py`), before calling `take_turn`: if `bound.spend_ceiling_usd is not
      None` and `limits.cost_ceiling_usd is None`, build a `replace()`d `Guardrails` with
      `cost_ceiling_usd = bound.spend_ceiling_usd - spent_so_far()` and pass that to `take_turn`
      instead of `limits`. Otherwise pass `limits` unchanged.
- [x] 2.2 Confirm `main(unattended=False)` with neither flag set is untouched: the derivation is
      gated on `spend_ceiling_usd is not None`, which is `None` on that path by default.
- [x] 2.3 Correct `--cost-ceiling-usd`'s CLI help text: it no longer always means "unbounded by
      cost" when omitted — only when no cumulative ceiling is set either.

## 3. Verify

- [x] 3.1 New test fails against the pre-change code (confirm, then revert to prove it), passes
      after. Confirmed: stashed `loop.py` alone, ran the new test, got
      `AssertionError: Obtained: None, Expected: 1.0` — the exact S244 shape (executor sees an
      unbounded turn). Popped the stash back, test passes.
- [x] 3.2 `make check` green: lint clean, `ty` clean, 420 passed / 13 deselected, citations OK.
- [x] 3.3 Re-run `make check` after archiving: green again, 420 passed / 13 deselected.
