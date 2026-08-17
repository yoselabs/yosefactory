# board-projection/inbox Specification

## Purpose
A read-only mirror of git work items on an external board, plus an append-only command inbox that
turns board-side actions into ordinary backlog/question events — so the board can be deleted and
rebuilt from git at any time, and every command Denis sends from it either lands or tells him why
it did not (architecture.md §7).
## Requirements
### Requirement: The board is authoritative for nothing

`project_all()` SHALL only read backlog items and write to the board adapter. No function in this
capability SHALL make a decision — pick an item, change a state, resolve a block — by reading from
the adapter. The adapter is a write-only mirror from git's perspective and a read-only inbox from
the board's perspective; the two directions SHALL NOT be combined into one read used for a
decision.

#### Scenario: Projection never branches on board state

- **WHEN** `project_all()` runs
- **THEN** its only read is `backlog.items()` / `question` logs on disk
- **AND** it never calls `adapter.list_events()` or inspects a board issue's own state to decide
  what to write

### Requirement: Projection is re-derivable from git alone

Deleting every artifact `project_all()` has created on the board and re-running it SHALL reproduce
an equivalent board: the same set of (item id, title, state) triples, independent of any cache,
mapping file, or prior run's return value.

#### Scenario: A destroyed board re-projects identically

- **WHEN** every issue `project_all()` created for a set of items is deleted from the board
- **AND** `project_all()` is run again against the same items
- **THEN** the re-projected board's (item id, title, state) triples equal the pre-destruction
  snapshot
- **AND** no file other than the board itself and the git items was consulted to produce the match

#### Scenario: Ref resolution has no other source of truth

- **WHEN** `open(item)` is called for an item that already has a board thread
- **THEN** it is found by searching the board for the item's id marker, never by reading a
  persisted mapping file
- **AND** if no thread is found, one is created and marked with the item's id

### Requirement: The BoardAdapter interface is message + thread + state-field

A `BoardAdapter` SHALL expose exactly: `list_events(since)`, `open(item) -> ref`,
`project(item, ref)`, `comment(ref, body)`, `close(ref, resolution)`. No adapter-specific method
SHALL be required by `project_all()` or `ingest()` — a second adapter (e.g. Forgejo) SHALL be able
to implement the same five methods without either function changing.

#### Scenario: project_all and ingest use only the five methods

- **WHEN** `project_all()` or `ingest()` runs against any adapter implementing the Protocol
- **THEN** no method is called on the adapter object other than the five named above

### Requirement: A command is an event, and reuses the existing event vocabulary

An inbound board command SHALL be represented as `Event {event_id, ts, actor, type, payload}`, with
`type` one of `set_priority`, `answer`, `cancel`. Applying an event SHALL append exactly one
existing, already-legal event to the target log — `priority_set` (backlog-item-format), `answered`
(question-frame), or `cancelled` (backlog-item-format) — through the same `runtime.turn.append()`
primitive every other writer in this repository uses. No new event name SHALL be added to either
vocabulary by this capability.

#### Scenario: A priority command appends priority_set

- **WHEN** a `set_priority` event with `payload.priority` arrives for a known item
- **THEN** a `priority_set` event is appended to that item's log with the given priority
- **AND** the item's fold reflects the new priority on the next read

#### Scenario: An answer command appends answered

- **WHEN** an `answer` event arrives naming a question id and an answer
- **THEN** an `answered` event is appended to that question's log
- **AND** the existing `runtime.turn.apply_answers()` mechanism — unmodified by this capability —
  unblocks the item that was waiting on it on its next invocation

### Requirement: Command application is idempotent by event_id

Every board event `ingest()` processes, applied or rejected, SHALL be recorded exactly once in an
append-only log keyed by the board's own `event_id`. Re-running `ingest()` over a window that
includes an already-recorded `event_id` SHALL NOT re-apply it.

#### Scenario: A re-ingested event is not re-applied

- **WHEN** `ingest()` is run twice over a window containing the same board event
- **THEN** the target log gains exactly one new line from that event, not two

#### Scenario: The consumer offset is derived, not stored separately

- **WHEN** `ingest()` computes what to ask the adapter for next
- **THEN** it is computed by folding the consumed-log, never read from a second field that could
  disagree with it

### Requirement: A rejected command is visible on the board, never silent

When a board event cannot be applied — the named item or question does not exist, or appending the
derived event is refused by the target log's own fold — `ingest()` SHALL post a reply naming the
reason via `adapter.comment()` on the same thread the command arrived on, and SHALL record the
rejection in the consumed-log. `ingest()` SHALL NOT raise out of a single command's rejection; one
bad command SHALL NOT stop the rest of the batch from being processed.

#### Scenario: An illegal transition is rejected with a reason, on-thread

- **WHEN** a `set_priority` command arrives for an item that is already terminal
- **THEN** no `priority_set` event is appended
- **AND** a comment naming the refusal is posted on the same board thread
- **AND** the event is recorded as rejected in the consumed-log

#### Scenario: One rejection does not block the rest of the window

- **WHEN** a window of unconsumed events contains one that is malformed and one that is valid
- **THEN** the valid event is still applied
- **AND** the malformed one is rejected and recorded, in either order

### Requirement: GitHub Issues implements the adapter without becoming the interface

The GitHub Issues adapter SHALL implement `list_events`/`open`/`project`/`comment`/`close` using
`gh` CLI subprocess calls scoped to one named repository per adapter instance. It SHALL NOT expose
any GitHub-specific concept (label, milestone, reaction) through the `BoardAdapter` Protocol itself
— those are implementation details of `project()`'s own rendering, not part of the interface.

#### Scenario: The adapter is constructed against exactly one repository

- **WHEN** a `GitHubIssuesAdapter` is constructed
- **THEN** every `gh` call it makes names that repository explicitly
- **AND** no call omits `--repo` or relies on the current directory's git remote

