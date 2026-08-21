## MODIFIED Requirements

### Requirement: The frame is not the channel for how a run is invoked

A work item's frame carries what the work **is** — goal, method, assumptions — and those are claims
that can be falsified, so they persist in the item's trail and are compared across runs.

How to run the work — which skill to follow, where to write the proposal, and which vocabulary
defines the event names and fields it may report — SHALL travel separately from the frame. It is
plumbing: it cannot be falsified, only go stale, and it SHALL NOT appear in the item's trail.

#### Scenario: The agent's instructions do not enter the item's frame

- **WHEN** a turn invokes the agent on an item
- **THEN** the frame it passes carries only the item's own goal, method and assumptions
- **AND** the skill and the proposal path are passed beside it, not within it

#### Scenario: The trail records no plumbing

- **WHEN** an item's trail is read after any number of turns
- **THEN** no skill name and no proposal path appears in it

#### Scenario: The event vocabulary reference is plumbing too

- **WHEN** a turn invokes the agent on an item
- **THEN** the agent is told where the event vocabulary is defined, passed beside the frame in the
  same channel as the skill and the proposal path
- **AND** the frame itself carries no event name, no required-field list, and no vocabulary reference

#### Scenario: The write instruction reminds the agent to check required fields

- **WHEN** a turn invokes the agent on an item
- **THEN** the instruction telling the agent to write its proposal is accompanied by a directive to
  check the vocabulary for the event's required fields before writing
- **AND** neither the frame, the skill, nor the invocation prompt restates any event's required
  field names — the vocabulary file remains the sole definition
