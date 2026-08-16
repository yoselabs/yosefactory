# turn-cycle Specification

## MODIFIED Requirements

### Requirement: Answers waiting in the repository are applied before classification

Before classifying, a turn SHALL read the durable question records and SHALL apply any answer that
resolves a block, returning the affected item to the state its block recorded.

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
