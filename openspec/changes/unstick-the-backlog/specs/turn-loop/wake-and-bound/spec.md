## MODIFIED Requirements

### Requirement: The loop's own turns cost nothing when nothing is eligible

`run_loop` SHALL NOT introduce any executor invocation, git operation beyond a `HEAD` read, or spend
beyond what `take_turn` itself would already incur for the same queue state.

A backlog holding **no item at all**, or holding only items already reclaimed/poisoned into a
terminal state, SHALL produce only `nothing-ready` turns, each committing a ledger record and costing
$0 — `take_turn`'s own `target is None and not should_plan(...)` branch never starts an executor, and
the loop must not add spend on top of that.

A backlog holding a **non-ready, non-terminal item that is not `claimed`/`doing`** (e.g. `failed`,
`blocked`, `snoozed`) is a different case (`turn-cycle`'s "Only live claims suppress planning"): such
an item does not make `should_plan` false, so the loop plans instead of reporting `nothing-ready` —
this SHALL cost exactly what an empty backlog's planning turn already costs, no more, and is bounded
by the same `LoopBound` this requirement's own next section describes, not by this one.

**Reason, carried with the rule:** this is what makes the loop's own self-chaining and bound receipts
runnable for real, repeatedly, without billing, for the case that genuinely has nothing to do —
`take_turn`'s `target is None and not should_plan(...)` branch never starts an executor, and the loop
must not add spend on top of that. A backlog that is not empty but is entirely stuck is a different,
deliberate case (`unstick-the-backlog`): planning around dead items costs the same as planning around
no items, which is a bounded, already-priced cost, not a new unbounded one.

#### Scenario: A quiescent backlog produces free, self-chained turns

- **WHEN** the queue holds no item at all across several iterations
- **THEN** each iteration completes with `Outcome.NOTHING_READY`, no executor is invoked, and
  cumulative recorded spend for the loop's run stays $0

#### Scenario: A backlog of only stuck items plans instead of freezing, at bounded cost

- **WHEN** the queue holds only `failed`, `blocked`, or `snoozed` items — none `ready`, none
  `claimed`/`doing` — across several iterations
- **THEN** each iteration plans (invokes an executor) rather than reporting `nothing-ready`
- **AND** the cumulative cost across those iterations is bounded by the same `LoopBound` that already
  bounds an empty backlog's planning cadence, not left unbounded by this requirement
