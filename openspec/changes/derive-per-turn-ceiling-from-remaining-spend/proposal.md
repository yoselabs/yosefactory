## Why

K [[S244]]: an unattended loop configured with `--spend-ceiling-usd 2.00` and no `--cost-ceiling-usd`
spent $8.18 before it stopped. `--spend-ceiling-usd` is the loop's cumulative bound, checked only
*between* iterations (`turn-loop/wake-and-bound`); `--cost-ceiling-usd` bounds one turn, and is
optional. With the second absent, a single turn ran unbounded by cost, and the cumulative check
fired only after the money was already spent. `docker-compose.yml:44` passed only the first flag —
but the defect is structural, not a missing line in one file: nothing stopped a caller from setting
a cumulative ceiling and no per-turn one, and the CLI help text for `--cost-ceiling-usd` said
"omitted, a turn is unbounded by cost" without qualification.

`factory-state/.github/workflows/take-a-turn.yml:534` already avoids this by passing both flags
from one number, by convention. This change makes that the structural default instead of a
convention one caller happens to follow.

## What Changes

- When `LoopBound.spend_ceiling_usd` is set and the caller did not supply an explicit
  `Guardrails.cost_ceiling_usd`, `run_loop` now derives one before each turn: the cumulative
  remaining budget (`spend_ceiling_usd - spend recorded so far`). An explicit `cost_ceiling_usd`
  is left untouched — both flags may still be given independently, unchanged from before.
- A caller who sets no cumulative ceiling at all (`main(unattended=False)`, unchanged) sees no
  behavior change: the derivation only fires when `spend_ceiling_usd` is set.
- `--cost-ceiling-usd`'s CLI help text is corrected: omitted no longer always means "unbounded by
  cost" — it means that only when no cumulative ceiling is set either.

## What This Does Not Do

- **Does not make `--cost-ceiling-usd` a hard preventive bound.** `claude-executor/cost-ceiling`
  already states, and this change does not change, that the executor's own `--max-budget-usd` is a
  **post-hoc detector**: it stops the *next* internal step of the `claude -p` process once a
  cumulative figure is crossed, and does not interrupt work already in flight. Measured elsewhere in
  that spec: a $0.02 cap observed $0.048 spent before the stop fired — 2.4x. Deriving a tighter
  per-turn number from the remaining cumulative budget shrinks the blast radius of the missing-flag
  defect; it does not turn the underlying mechanism into a hard ceiling. That would be a claim about
  the executor, which this change does not touch.
- **Does not change `docker-compose.yml`.** It already passes only `--spend-ceiling-usd`; that is
  now the case the derivation exists for, so the file needs no edit. `take-a-turn.yml` passes both
  explicitly already, so it is also unaffected (explicit wins).

## Capabilities

### Modified Capabilities
- `turn-loop/wake-and-bound`: when a cumulative spend ceiling is set and no per-turn ceiling was
  given explicitly, the loop now derives one from the remaining cumulative budget before each turn,
  instead of leaving the turn unbounded by cost.

## Impact

- `src/yosefactory/runtime/loop.py` — `run_loop`'s per-iteration bound check; `main()`'s
  `--cost-ceiling-usd` help text.
- Tests: `tests/runtime/test_loop.py` — a turn with a cumulative ceiling set and no explicit
  per-turn ceiling receives a derived `Guardrails.cost_ceiling_usd` equal to the remaining budget;
  shown to fail before this change (the executor receives `cost_ceiling_usd=None`) and pass after.

## Non-goals

- Not adding a preventive mid-turn kill switch to the executor lane — no such mechanism exists in
  the pinned `claude` binary (`claude-executor/cost-ceiling`), and building one is out of this
  change's scope.
- Not requiring `--cost-ceiling-usd` on the unattended entrypoint, and not refusing to start
  without one — the derivation makes an explicit per-turn flag unnecessary for safety rather than
  mandatory.
- Not touching `docker-compose.yml` or `take-a-turn.yml`.
