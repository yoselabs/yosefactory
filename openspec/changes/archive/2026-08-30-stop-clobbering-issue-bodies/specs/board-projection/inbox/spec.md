# board-projection/inbox Specification

## ADDED Requirements

### Requirement: Projection never removes text it did not write

`GitHubIssuesAdapter.project()` SHALL NOT overwrite an issue body once that body already carries
the item marker (`_extract_item_id` finds it). It SHALL PATCH `title` unconditionally on every
call, and SHALL NOT include a body in that PATCH once the marker is present — any text a human
added to the issue after the marker was written, including a full specification, SHALL survive
every subsequent projection unchanged.

State (`item.state`) SHALL be carried by the title alone (`[state] goal`); the rendered body used
by `open()`'s create path SHALL NOT duplicate it, so there is no body-side copy of state that
`project()`'s no-longer-touching-the-body behaviour would leave permanently stale.

When the marker is absent from the current body — the sole legitimate case being `ingest()`'s
create path projecting a freshly-adopted, possibly human-authored, markerless issue — `project()`
SHALL prepend the marker line to the existing body and SHALL NOT discard, reorder, or truncate
any text the body already held.

#### Scenario: A human-authored specification survives an ordinary projection

- **WHEN** `project(item, ref)` is called against an issue whose body already carries `item`'s
  marker, followed by arbitrary human-written text
- **THEN** the issue's body after the call is byte-for-byte identical to before the call
- **AND** the issue's title reflects `item`'s current state and goal

#### Scenario: A state change still reaches the issue, via the title only

- **WHEN** an item's state changes and `project()` is called against its already-marked issue
- **THEN** the title's `[state]` segment reflects the new state
- **AND** the body is not part of the PATCH request `project()` sends

#### Scenario: A markerless issue gains the marker without losing its own text

- **WHEN** `project(item, ref)` is called against an issue with no item marker in its body yet
- **THEN** the resulting body is the marker line followed by the issue's prior body content,
  unmodified
- **AND** a subsequent `project()` call against the same issue makes no further body write

#### Scenario: `open()`'s creation path is unaffected

- **WHEN** `open()` creates a fresh issue for an item with no existing thread
- **THEN** the created issue's body carries the item marker and the item's rendered goal, exactly
  as before this requirement existed
