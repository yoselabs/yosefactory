## MODIFIED Requirements

### Requirement: The loop is bounded, and the bound is mandatory

`LoopBound.max_iterations` SHALL be a required positive integer with no default; a `LoopBound`
constructed with a non-positive or missing `max_iterations` SHALL be refused before the loop runs.
`LoopBound.spend_ceiling_usd` MAY be `None` (no spend cap) or a positive number. `run_loop` SHALL
stop the first time either bound holds:

- the number of turns run reaches `max_iterations`, or
- (when `spend_ceiling_usd` is set) cumulative spend recorded in the durable spend ledger since the
  loop started reaches `spend_ceiling_usd`.

The spend check SHALL be evaluated again after each wake-wait, before the next `take_turn` call —
not only once per iteration before the wait — so that spend recorded while the loop was idle still
stops the next turn from starting.

**Reason, carried with the rule:** a self-chaining loop is the first mechanism in this program
capable of spending money with nobody between iterations. A bound with an infinite mode, or a
spend check that can be satisfied and then falsified during a long wait, both defeat the property
the bound exists for.

**When `spend_ceiling_usd` is set and the caller supplied no explicit per-turn
`Guardrails.cost_ceiling_usd`, `run_loop` SHALL derive one before each turn: the cumulative
remaining budget (`spend_ceiling_usd` minus spend recorded so far), rather than leaving the turn
unbounded by cost.** An explicit `cost_ceiling_usd` SHALL be left untouched — the derivation applies
only when the caller supplied none. When `spend_ceiling_usd` is `None`, no derivation happens and a
turn's cost bound is exactly what the caller passed (unchanged, including `None`).

**Reason, carried with the rule:** K [[S244]] — a loop configured with a $2.00 cumulative ceiling
and no per-turn ceiling spent $8.18 before the cumulative check, evaluated only between turns, ever
saw the overspend. A cumulative ceiling with no per-turn bound is not a spending limit; it is a stop
condition evaluated at a boundary a single turn can cross arbitrarily far. This does not turn the
executor's own per-turn ceiling into a preventive bound — `claude-executor/cost-ceiling` already
documents it as a post-hoc detector, unchanged by this — but it ensures the caller never gets *no*
per-turn number by omission when a cumulative one is in force.

#### Scenario: An unbounded `LoopBound` is refused
- **WHEN** `LoopBound` is constructed with `max_iterations=0`, a negative value, or omitted
- **THEN** construction raises before any turn runs

#### Scenario: The loop stops exactly at `max_iterations`
- **WHEN** `max_iterations` turns have completed and no spend ceiling is set
- **THEN** the loop returns with `StopReason.MAX_ITERATIONS` and no further turn runs

#### Scenario: Spend accrued during a wait still stops the next turn
- **WHEN** cumulative recorded spend crosses `spend_ceiling_usd` while the loop is waiting for a
  wake condition, and the bound had not yet been reached at the top of that iteration
- **THEN** the loop returns with `StopReason.SPEND_CEILING` without calling `take_turn` again

#### Scenario: No spend ceiling means no spend-based stop
- **WHEN** `spend_ceiling_usd` is `None`
- **THEN** the loop runs until `max_iterations` regardless of recorded spend

#### Scenario: A cumulative ceiling with no explicit per-turn ceiling derives one
- **WHEN** `bound.spend_ceiling_usd` is set to `2.00`, `$1.00` has already been recorded as spent
  this run, and the caller's `Guardrails.cost_ceiling_usd` is `None`
- **THEN** the turn about to run is invoked with a per-turn cost ceiling of `1.00` (the remaining
  cumulative budget), not with no per-turn ceiling at all

#### Scenario: An explicit per-turn ceiling is never overridden by the derivation
- **WHEN** `bound.spend_ceiling_usd` is set and the caller's `Guardrails.cost_ceiling_usd` is also
  set explicitly
- **THEN** the turn is invoked with the caller's own value, unchanged by any derivation

#### Scenario: No cumulative ceiling means no derivation either
- **WHEN** `bound.spend_ceiling_usd` is `None`
- **THEN** the turn's per-turn cost ceiling is exactly what the caller passed, including `None`,
  with no value derived or substituted
