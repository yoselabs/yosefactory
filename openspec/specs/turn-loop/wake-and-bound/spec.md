# turn-loop/wake-and-bound Specification

## Purpose
TBD - created by archiving change add-turn-loop. Update Purpose after archive.
## Requirements
### Requirement: The loop self-chains `take_turn` after every completed turn

`run_loop` SHALL call `runtime.turn.take_turn` at least once, and after each call SHALL
re-evaluate its bound and its wake conditions rather than returning, until the bound stops it.
Each call to `take_turn` SHALL be a complete, independent transaction — the loop SHALL NOT hold
an item, a lock, or a decision across iterations beyond what `take_turn` itself already persists.

**Reason, carried with the rule:** `take_turn` is a function; nothing before this change called it
more than once from inside a single process. The self-chaining is the entire gap between "a
function exists" and "a factory runs."

#### Scenario: A turn's outcome does not stop the loop
- **WHEN** `take_turn` returns any outcome and the bound has not been reached
- **THEN** the loop waits for the next wake condition and calls `take_turn` again

#### Scenario: The very first turn runs without waiting for a wake condition
- **WHEN** `run_loop` starts
- **THEN** it calls `take_turn` immediately, recording `WakeReason.STARTUP`, without evaluating
  any of the three wake conditions or sleeping first

### Requirement: Three wake conditions, and the loop wakes on whichever fires first

Between turns, `run_loop` SHALL wait until at least one of the following holds, and SHALL record
which one triggered each turn:

1. **Ready item** — an item in the queue is `state == "ready"`.
2. **External event** — the queue repository's own `HEAD` commit has changed since the loop last
   checked it.
3. **Heartbeat** — `WakeConfig.heartbeat_seconds` has elapsed since the previous turn, and neither
   of the above has fired.

The loop SHALL check condition 1 before condition 2, and condition 2 before condition 3, on every
poll — a ready item or a moved `HEAD` SHALL wake the loop before its heartbeat interval elapses.

**Reason, carried with the rule:** dropping the heartbeat leaves a fully quiescent backlog (nothing
ready, nothing blocked, nothing recently committed) with no turn ever firing again — a stall
architecture.md §8 already names as this platform's signature failure, relocated from "no advance
in the window" to "no turn at all." Checking cheapest-first (an in-memory glob before a git
subprocess before a clock read) keeps the common poll free.

#### Scenario: A ready item wakes the loop before the heartbeat
- **WHEN** an item transitions to `ready` while the loop is waiting, and the heartbeat interval has
  not yet elapsed
- **THEN** the loop wakes with `WakeReason.READY_ITEM` and does not wait for the heartbeat

#### Scenario: A commit landing in the queue wakes the loop even with no ready item
- **WHEN** the queue repository's `HEAD` changes while the loop is waiting, and no item is
  `ready`
- **THEN** the loop wakes with `WakeReason.EXTERNAL_EVENT`

#### Scenario: The heartbeat wakes the loop when nothing else has happened
- **WHEN** no item becomes ready and the queue's `HEAD` does not move for the full
  `heartbeat_seconds` interval
- **THEN** the loop wakes with `WakeReason.HEARTBEAT` and calls `take_turn`

### Requirement: The wake reason is durable, readable from disk without the in-memory report

For every turn `run_loop` runs, it SHALL write a durable record of which wake condition triggered
that turn, keyed to the same run so a later reader can join the two without holding the
`LoopReport` the run produced. The record SHALL be committed to the queue repository, not left as
an uncommitted working-tree file.

**Reason, carried with the rule:** `LoopReport.steps` lives in memory and is gone once the process
exits or a caller only logs a summary. A loop whose only account of *why it woke* is its own return
value is exactly the shape S195 catalogued nine times over — a fact that exists in code and cannot
be read back. Article XII (`orchestration.md`) applies equally to this platform's own runtime: the
subject is `ledger/runs/`, not a Python object.

#### Scenario: A turn's wake reason survives the process that ran it
- **WHEN** a turn completes, whatever its outcome
- **THEN** a durable, committed record naming that turn's `run_id` and its wake reason exists in
  the queue repository, independent of any in-memory report

#### Scenario: The wake record joins to the turn record by run_id
- **WHEN** a reader has only the queue repository on disk, with no access to the process that ran
  the loop
- **THEN** the reader can determine, for a given `ledger/runs/` turn record, which of the three
  wake conditions produced it

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

