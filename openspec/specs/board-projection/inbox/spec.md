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

### Requirement: A command's effect is committed to git, not left in the working tree

Every event `ingest()` applies or rejects SHALL be committed to the target repository — the item
or question log it wrote to, and the consumed-log entry recording the outcome — using the same
commit path (`runtime.turn.commit()`, explicit pathspecs, platform trailers) every other writer in
this repository uses. `ingest()` SHALL NOT leave an applied command as an uncommitted working-tree
change.

**Reason, carried with the rule:** an uncommitted write does not move the queue's `HEAD`, so a
caller relying on `HEAD` movement to detect that something happened (`turn-loop/board-wiring`'s
`EXTERNAL_EVENT` wake) would never see it. A working-tree-only change is also invisible to `git
log`, to a push, and to any reader treating git as the source of truth — architecture.md §7's own
premise for why the board is safe to project publicly.

#### Scenario: An applied command is a real commit
- **WHEN** `ingest()` successfully applies a command
- **THEN** the target log's new event and the consumed-log's new entry are both present in a
  single commit
- **AND** the repository's working tree is clean with respect to those paths afterward

#### Scenario: A rejected command still commits the consumed-log entry
- **WHEN** `ingest()` rejects a command
- **THEN** the consumed-log's rejection entry is committed
- **AND** no partial, uncommitted state is left for either the target log or the consumed log

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

### Requirement: The live receipt against real GitHub is runnable on demand, outside `make check`

This capability's own `boardlive`-marked tests (`tests/board/test_reprojection.py`) SHALL be
runnable via a dedicated `make` target that is not part of `make check`'s default selection. The
target SHALL exist for the same reason `make test-live` does — the tests it runs mutate external
state and need `gh` auth, so joining `make check` would make every default build depend on network
access and credentials the marker itself declares it needs.

A change that touches `src/yosefactory/board/` SHALL run this target before merge — this is a
documented step, not a mechanically enforced gate, and the exclusion from `make check` stays in
place regardless (S243: excluding a check from the default suite is correct; never running it at
all is the defect this requirement closes).

#### Scenario: The marker is runnable without joining the default suite

- **WHEN** a developer runs `make test-boardlive`
- **THEN** it invokes `pytest -m boardlive` against `tests/board/`
- **AND** `make check` (and therefore `make test`) still excludes `boardlive` from its own run

#### Scenario: A board-touching change carries a live-receipt result

- **WHEN** a change modifies anything under `src/yosefactory/board/`
- **THEN** the change's own verification record names the verbatim result of `make test-boardlive`
  (or `pytest -q -m boardlive tests/board/`) run against `BOARD_REPO`, not only `make check`

### Requirement: The GitHub adapter records which identity it is reading and writing as

`GitHubIssuesAdapter` SHALL resolve the authenticated `gh` login on the first board read it
performs, cache it for the lifetime of the instance, and make it available so a failed or
unexpectedly short read is diagnosable after the fact. Resolution SHALL be best-effort — a failure
to resolve the login SHALL NOT block or alter the outcome of the read that triggered it. Resolving
or recording identity SHALL NOT read, print, log, or store a credential; only the login name (the
same value `gh auth status` already prints) is used.

#### Scenario: Identity is resolved on first read and cached

- **WHEN** a `GitHubIssuesAdapter` performs its first board read (`open`, `list_events`, or
  internal ref lookup)
- **THEN** the authenticated `gh` login is resolved once and held on the instance
- **AND** a subsequent read on the same instance does not resolve it again

#### Scenario: A failed call names the identity that made it

- **WHEN** a `gh api` call this adapter makes fails after identity has been resolved
- **THEN** the raised `BoardError`'s message includes the resolved identity alongside the
  repository name

#### Scenario: Identity resolution failing does not block the read

- **WHEN** resolving the authenticated login itself fails (no `gh` session at all)
- **THEN** the read that triggered resolution proceeds and fails or succeeds on its own terms,
  unaffected by the resolution failure

#### Scenario: No credential is ever read, printed, logged, or stored

- **WHEN** identity is resolved or recorded, at any point
- **THEN** no token, header, or other credential value is read, printed, logged, or persisted by
  this mechanism — only the login name

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

