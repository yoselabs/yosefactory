## MODIFIED Requirements

### Requirement: Classification is derived from state, never declared

A turn SHALL decide between planning and executing by reading the state of the backlog. It SHALL NOT
accept a flag, mode, stage name, or configuration value that selects the phase.

A turn SHALL plan when no item is eligible to be acted on, and SHALL act when at least one is.

**"Eligible to be acted on" is `eligible()`'s own predicate (`ready`), not a wider "anything is
happening" predicate.** Whether planning is additionally suppressed when no item is eligible is a
separate question, answered by "planning is suppressed while genuinely in flight" below — the two
SHALL NOT be conflated into one non-terminal check, because a non-terminal state with no route back
to `ready` (`failed`, `falsified`, `needs_split`) or with a route back nothing yet fires (`blocked`,
`snoozed`, absent the sweeper `eligible()`'s own docstring says does not exist) is not "happening" in
any sense that justifies withholding all future work.

#### Scenario: Empty backlog selects planning

- **WHEN** a turn runs and the backlog contains no item eligible for action
- **THEN** the turn plans

#### Scenario: A ready item selects execution

- **WHEN** a turn runs and at least one item is eligible for action
- **THEN** the turn acts on one such item and does not plan

#### Scenario: A phase flag is refused

- **WHEN** a caller supplies an argument that names the phase
- **THEN** the turn fails without running an agent, and the failure names the phase as state-derived

#### Scenario: A backlog of only stuck items still selects planning

- **WHEN** a turn runs and every item in the backlog is `failed`, `falsified`, `needs_split`,
  `blocked`, or `snoozed` — none of them `ready`, none of them `claimed` or `doing`
- **THEN** the turn plans
- **AND** this holds regardless of how many such items exist or how long they have been in that
  state

### Requirement: Answers waiting in the repository are applied before classification

Before classifying, a turn SHALL read the durable question records and SHALL apply any answer that
resolves a block, returning the affected item to the state its block recorded.

A turn SHALL also reclaim any expired lease before classifying: for every item in `claimed` or
`doing` whose most recent lease's `expires_at` has passed, the turn SHALL append `reclaimed`
(returning it to `ready`) or, if the attempt ceiling (`Guardrails.max_attempts`) has been reached,
`failed` followed by `poisoned` instead. Both sweeps run in the same deterministic, agent-free step —
neither invokes an executor, and both run before `eligible()`/`should_plan()` are evaluated, so an
item either sweep moves is visible to classification in the same turn that moved it.

Every path this sweep step appends to SHALL be included among the paths the turn's eventual commit
stages, whatever this turn's classification or outcome — a path written by the sweep and never named
in a commit is invisible to `git commit -- <paths>` (Article V) and, under a configuration where
`places.queue` and `places.workspace` coincide, misreads as the agent's own uncommitted work.

A turn SHALL NOT read a steering inbox: no such format exists in this repository. This is a known
gap against the end-to-end design and SHALL be recorded as one rather than filled by invention.

**A run stopped by a permission denial SHALL raise a question, not merely narrow to a ledger
outcome.** When an executor result carries `blocked_kind: needs_approval`, the turn SHALL write a
question (`asked`, carrying `deadline`, `on_timeout`, `return_to`, and a correlation id) before
suspending the item, and SHALL block the item on that question exactly as a `blocked` proposal
written by the agent itself would. A denial that produces a turn record and no question is not a
suspension; it is a stall this requirement exists to prevent.

**Reason, carried with the rule:** `needs_approval` is named resumable (`protocol/turn.py`'s
`RESUMABLE`), distinct from `refused`, precisely because something can arrive to clear it. A
resumable ending that writes nothing an answer could resolve is resumable in name only — the item
acquires no deadline, no timeout policy, no way for a later turn to find it, and is not even visible
to the classifier that would otherwise pick it up once `ready`. S172 (every loop must close) is
violated at the point the loop opens, not at some later point it fails to close.

**Reason, carried with the rule, for the reclaim half:** `expires_at` was written (`claimed`'s own
required field) and read by nothing before this requirement — a turn that died after claiming an item
left it in `doing` forever, indistinguishable in effect from `failed`'s own dead end. The
commit-scoping half of this requirement exists because the *first* sweep this repository ever wrote
(`apply_answers`) shipped without it: its return value naming the items it moved has been discarded
since it was written, so those items' `unblocked` lines have been landing on disk, uncommitted, all
along.

#### Scenario: An answered question unblocks its item before the turn classifies

- **WHEN** a turn starts and a question that blocked an item has been answered since the last turn
- **THEN** the item returns to the state recorded at block time
- **AND** the item is eligible for action in this same turn

#### Scenario: An unanswered question leaves its item blocked

- **WHEN** a turn starts and a blocking question is still open
- **THEN** the item it blocks is not eligible for action

#### Scenario: A permission denial suspends the item on a question

- **WHEN** an executor result reports a permission denial (`blocked_kind: needs_approval`)
- **THEN** a question is written, carrying a `deadline`, an `on_timeout` policy, and
  `return_to` set to the item's state before the run
- **AND** the item is appended a `blocked` event whose `awaiting.ref` names that question
- **AND** the turn's own ledger row is written exactly as it is today, unchanged by this requirement

#### Scenario: A refusal does not raise a question

- **WHEN** an executor result reports a refusal (`blocked_kind: refused`)
- **THEN** no question is written and the item is not suspended on one — D019: the answer to a
  refusal is a human re-deciding the goal, not a resumption

#### Scenario: An expired lease is reclaimed before classification

- **WHEN** a turn starts and an item is `claimed` or `doing` with an `expires_at` in the past, below
  the attempt ceiling
- **THEN** the sweep appends `reclaimed`, returning the item to `ready`
- **AND** the same turn may pick that item for its own claim if it ranks highest

#### Scenario: An exhausted lease is poisoned before classification, not reclaimed again

- **WHEN** a turn starts and an item's expired lease's `attempt` has reached the configured ceiling
- **THEN** the sweep appends `failed` then `poisoned` instead of `reclaimed`
- **AND** the item is terminal and no longer suppresses planning or consumes a future claim

#### Scenario: Every event the sweep step writes is committed with the turn, not left on disk

- **WHEN** the sweep step (answers applied, leases reclaimed or poisoned) writes to one or more item
  logs, and the turn goes on to plan, act, or report `nothing-ready`
- **THEN** every path the sweep touched is present in the same commit the turn's own outcome is
  recorded in
- **AND** none of those paths appears as an uncommitted change in the tree afterward

## ADDED Requirements

### Requirement: Only live claims suppress planning

`should_plan` SHALL return false only when at least one item is `claimed` or `doing` — no other
non-terminal state (`failed`, `falsified`, `needs_split`, `blocked`, `snoozed`) SHALL suppress
planning. Because the sweep step above reclaims or poisons every expired lease before this predicate
is evaluated, a `claimed`/`doing` item that still suppresses planning at this point is one whose
lease has not yet expired — genuinely in flight, not merely not-yet-cleaned-up.

**Reason, carried with the rule:** S1021 — one item in any non-terminal, non-eligible state forbade
all future planning forever, for free, because the prior predicate treated every non-terminal state
as "in flight" including several with no route back to `ready` at all. A backlog holding only such
items is now planned around exactly as an empty backlog already is, bounded by the same
`LoopBound.max_iterations`/`spend_ceiling_usd` that already bounds planning-turn cost — see
`design.md` for why this does not introduce an unbounded new cost.

#### Scenario: A single failed item does not block planning forever

- **WHEN** the backlog holds one `failed` item and nothing else, indefinitely, across many turns
- **THEN** every one of those turns plans
- **AND** none of them is forbidden from planning by the failed item's continued presence

#### Scenario: A live claim still blocks planning

- **WHEN** the backlog holds one item in `claimed` or `doing` with an unexpired lease, and no item is
  `ready`
- **THEN** the turn does not plan
- **AND** it reports `nothing-ready` instead, exactly as before this change
