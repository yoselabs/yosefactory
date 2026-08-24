## MODIFIED Requirements

### Requirement: A command is an event, and reuses the existing event vocabulary

An inbound board command SHALL be represented as `Event {event_id, ts, actor, type, payload}`, with
`type` one of `set_priority`, `answer`, `cancel`, `create`. Applying an event SHALL append exactly
one existing, already-legal event to the target log — `priority_set` (backlog-item-format),
`answered` (question-frame), `cancelled` (backlog-item-format), or `created` (backlog-item-format)
— through the same `runtime.turn.append()` primitive every other writer in this repository uses.
No new event name SHALL be added to either vocabulary by this capability.

Unlike the other three, a `create` event SHALL NOT be produced by parsing a comment's `/word`
syntax. It SHALL be produced when `list_events()` finds a board thread carrying no item marker at
all — the act of opening such a thread is the command.

#### Scenario: A priority command appends priority_set

- **WHEN** a `set_priority` event with `payload.priority` arrives for a known item
- **THEN** a `priority_set` event is appended to that item's log with the given priority
- **AND** the item's fold reflects the new priority on the next read

#### Scenario: An answer command appends answered

- **WHEN** an `answer` event arrives naming a question id and an answer
- **THEN** an `answered` event is appended to that question's log
- **AND** the existing `runtime.turn.apply_answers()` mechanism — unmodified by this capability —
  unblocks the item that was waiting on it on its next invocation

#### Scenario: A create command appends created

- **WHEN** a `create` event arrives naming a board thread with no existing item
- **THEN** a `created` event is appended to a freshly allocated item's log, carrying a `frame`
  built from the thread's own title/body
- **AND** the item's fold shows state `ready` on the next read

### Requirement: Projection is re-derivable from git alone

Deleting every artifact `project_all()` has created on the board and re-running it SHALL reproduce
an equivalent board: the same set of (item id, title, state) triples, independent of any cache,
mapping file, or prior run's return value.

**The same no-cache discipline governs intake in the other direction.** Whether a board thread has
already produced an item SHALL be answered by reading that thread's own body for the item marker
at the moment `list_events()` runs — never by a separately stored "already ingested" flag. This is
what "no thread with a marker is ever offered again as a `create` candidate" means structurally:
the marker is written back onto the same thread before the ingesting call returns, so the very
next read of that thread's body already shows it as ingested.

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

#### Scenario: A thread with a marker is never a create candidate

- **WHEN** `list_events()` scans a board thread whose body already carries an item marker
- **THEN** it is treated as an existing item's thread — its comments are parsed for
  `set_priority`/`answer`/`cancel` — and never as a `create` candidate

## ADDED Requirements

### Requirement: An unmarked board thread becomes a new backlog item

`list_events()` SHALL emit a `create` event for every board thread whose body carries no item
marker, instead of silently skipping it. The event's payload SHALL carry the thread's title and
body exactly as read at the moment of the call — never a value cached from an earlier read.

Applying a `create` event SHALL allocate a new item id, build a frame from the thread's title
(`goal`) and body (`method`), fill `assumptions` with a fixed statement that the frame was not
rigorized, and append `created` (backlog-item-format) to the new item's log with `loop:
"board-intake"`. It SHALL NOT refuse a thread for having an empty or short body, and SHALL NOT
block the new item on a question waiting for a better frame — both are out of scope for this
capability (`M440`'s rigorizer applies uniformly to every intake door, not specially to this one).

Immediately after the new item's log is written, `ingest()` SHALL call `adapter.project(item,
ref)` on the same thread the `create` event arrived on, so the thread carries the new item's
marker before `ingest()` returns for that event.

#### Scenario: An issue with no marker becomes a new item

- **WHEN** `list_events()` is called and a board thread's body carries no item marker
- **THEN** a `create` event is produced for that thread, carrying its current title and body

#### Scenario: A thin issue still produces a legal frame

- **WHEN** a `create` event's payload carries an empty body
- **THEN** the new item's `created` event still supplies non-empty `goal`, `method`, and
  `assumptions`, and the item's fold is `ready`

#### Scenario: The marker is written back before ingest returns

- **WHEN** a `create` event is applied
- **THEN** `adapter.project()` is called on the source thread with the newly created item
- **AND** a `list_events()` call made afterward against the same board state no longer offers
  that thread as a `create` candidate

#### Scenario: A rejected create is visible on the thread

- **WHEN** a `create` event cannot be applied — appending the derived `created` event is refused
  by the new log's own fold
- **THEN** no item log is left behind
- **AND** a comment naming the refusal is posted on the same board thread
- **AND** the event is recorded as rejected in the consumed-log, same as any other rejected command
