## ADDED Requirements

### Requirement: A turn carries what the attempt before it produced, in a channel separate from the frame

The frame SHALL remain a statement of the task ([[D019]]), amended only when the task itself
changes ([[D030]]). A second value — **inherited context** — SHALL be folded from the item's own
event log and passed to the executor alongside the frame, never merged into it.

Inherited context SHALL be folded from exactly four sources and no more: a gate rejection, an
`unblocked` event's answer text, a prior `failed` event's reason/retryable/attempt, and a
`released`/`reclaimed` event's reason. No other event — `note` included — SHALL feed this channel.

A turn with no prior attempt on the item (its log holds none of the four source events) SHALL pass
an empty context; the executor SHALL NOT be told anything happened when nothing did.

#### Scenario: A rejected turn's successor is told what failed

- **WHEN** a turn's `done` proposal is rejected by the verification gate
- **THEN** the item's log gains a `gate_rejected` record with the gate's own report
- **AND** the next turn against the same item receives that report in its inherited context
- **AND** the frame passed to that next turn is byte-identical to the frame the rejected turn
  received — the two channels stay separate

#### Scenario: An answer reaches the agent that asked

- **WHEN** an agent blocks on a question and a human answers it
- **THEN** the turn that resumes the item receives the answer's text in its inherited context
- **AND** the frame passed to that turn does not change as a result of the answer

#### Scenario: `note` never enters inherited context

- **WHEN** an item's log carries one or more `note` events
- **THEN** none of their bodies appear in any turn's inherited context

#### Scenario: A first attempt inherits nothing

- **WHEN** a turn claims an item that has never been rejected, blocked, failed, released, or
  reclaimed
- **THEN** the inherited context passed to the executor is empty
