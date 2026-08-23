## MODIFIED Requirements

### Requirement: Classification is derived from state, never declared

A turn SHALL decide between planning and executing by reading the state of the backlog. It SHALL NOT
accept a flag, mode, stage name, or configuration value that selects the phase.

A turn SHALL plan when no item is eligible to be acted on, and SHALL act when at least one is.

**"Eligible to be acted on" is `eligible()`'s own predicate — `ready`, or `doing` whose most recent
event is `gate_rejected`** — not a wider "anything is happening" predicate. The second case resumes
the item's existing lease (same `attempt`, same `owner`) rather than claiming it fresh, per
ADR-0015's own choice that a gate rejection stays retryable within the same attempt
(`backlog-item-format`'s "`gate_rejected` never resets or reclassifies the item" carries the
transition-level guarantee this reads). Whether planning is additionally suppressed when no item is
eligible is a separate question, answered by "Only live claims suppress planning" below — the two
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

#### Scenario: A gate-rejected item is retried without waiting out its lease

- **WHEN** an item is `doing` and its most recent event is `gate_rejected`, and its lease has not
  yet expired
- **THEN** the item is eligible for action on the very next turn
- **AND** the turn that acts on it appends no new `claimed` or `started` event
- **AND** the turn reads `attempt` and `owner` from the lease already on the item, unchanged
