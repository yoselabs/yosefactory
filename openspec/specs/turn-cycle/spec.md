# turn-cycle Specification

## Purpose
One turn of the factory: read the repository, do exactly one thing, record what happened, commit, and
exit. The turn is the only unit that runs, and everything it needs to resume is on disk, so the next
turn may be a different process on a different machine days later.
## Requirements
### Requirement: A turn is a function of repository state

A turn SHALL read all the state it acts on from its queue (backlog items and questions) and SHALL
leave the state it produces in its queue and, for work carried out during the turn, in its
workspace. Nothing SHALL be passed from one turn to the next by any other means — no held process,
no session, no in-memory carry-over, no environment.

Queue and workspace SHALL be independently named locations (`turn-places`); a turn configured with
one location for both reads and writes exactly as a single-repository turn always has.

A turn SHALL perform, in order: acquire, classify, do exactly one item, record, commit, exit.

#### Scenario: A second turn resumes from the repository alone

- **WHEN** a turn completes and a second turn starts as a fresh process against the same queue
- **THEN** the second turn reads the first turn's committed queue effects and continues from them
- **AND** the second turn requires no argument, file, or variable produced by the first turn other
  than what the first turn committed to the queue

#### Scenario: A turn does exactly one item

- **WHEN** a turn reaches the do step with several items eligible
- **THEN** it acts on exactly one of them
- **AND** the remaining eligible items are untouched and remain eligible for a later turn

### Requirement: Classification is derived from state, never declared

A turn SHALL decide between planning and executing by reading the state of the backlog. It SHALL NOT
accept a flag, mode, stage name, or configuration value that selects the phase.

A turn SHALL plan when no item is eligible to be acted on, and SHALL act when at least one is.

#### Scenario: Empty backlog selects planning

- **WHEN** a turn runs and the backlog contains no item eligible for action
- **THEN** the turn plans

#### Scenario: A ready item selects execution

- **WHEN** a turn runs and at least one item is eligible for action
- **THEN** the turn acts on one such item and does not plan

#### Scenario: A phase flag is refused

- **WHEN** a caller supplies an argument that names the phase
- **THEN** the turn fails without running an agent, and the failure names the phase as state-derived

### Requirement: Steps one and two are deterministic and cost nothing

Acquiring state and classifying SHALL be performed without invoking an agent. A turn that finds
nothing to do SHALL exit without invoking an agent.

#### Scenario: Nothing ready costs no agent invocation

- **WHEN** a turn finds no item eligible for action and no planning trigger
- **THEN** no agent process is started
- **AND** the turn writes a turn record whose outcome is `nothing-ready`
- **AND** the turn exits successfully

#### Scenario: Nothing-ready is not success

- **WHEN** a reader examines a sequence of turn records
- **THEN** a `nothing-ready` record is distinguishable from an `advanced` record
- **AND** nothing in the turn treats `nothing-ready` as progress

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

### Requirement: The agent proposes exactly one typed event

The agent SHALL propose its result as one event, expressed as a single JSON object written to a path
the turn supplies. The turn SHALL reject a proposal containing more than one event for an item.

A planning turn SHALL be permitted to propose the creation of one or more new items; an acting turn
SHALL propose exactly one event against exactly one existing item.

The agent SHALL NOT decide what happens next. It reports what happened; the state graph determines
what follows.

#### Scenario: A single well-formed event is accepted

- **WHEN** the agent writes one event that is legal from the item's current state and carries every
  field that event requires
- **THEN** the turn appends it to the item's log

#### Scenario: More than one event is refused

- **WHEN** the agent writes a proposal containing two or more events for one item
- **THEN** the turn writes no event
- **AND** the turn record's outcome is `failed`, naming the refusal

#### Scenario: A missing or unparseable proposal is a failure, not an absence

- **WHEN** the agent finishes without writing a proposal, or writes one that is not a JSON object
- **THEN** the turn record's outcome is `failed`
- **AND** the item's log is unchanged

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

### Requirement: Invariants are checked by the fold, not by the prompt

The turn SHALL validate a proposed event by folding the item's log with the event applied. An
unknown event, an illegal transition from the current state, a missing required field, or a field
that fails its pattern SHALL cause the turn to reject the proposal.

A rejected proposal SHALL NOT survive the turn: the item's log SHALL be left byte-for-byte as it was.
This is the property that makes a failed turn safe to retry — a later turn reads an item that carries
no trace of the refused attempt.

The instructions given to the agent SHALL NOT restate these invariants as rules for the agent to
obey. Enforcement is deterministic and lives outside the prompt.

#### Scenario: An illegal transition is rejected and leaves no trace

- **WHEN** the agent proposes an event that is not legal from the item's current state
- **THEN** the item's log is byte-for-byte what it was before the turn
- **AND** the turn record's outcome is `failed`, naming the illegal transition

#### Scenario: A missing required field is rejected

- **WHEN** the agent proposes an event that omits a field the event requires
- **THEN** the event is not written and the turn's outcome is `failed`

### Requirement: A done transition requires an independent check

The turn SHALL NOT write a `done` event on the agent's report alone. Before writing `done`, the turn
SHALL run the independent verification gate against the repository, and SHALL write the event only
if the gate passes.

#### Scenario: The gate fails and done is not written

- **WHEN** the agent proposes `done` and the verification gate fails
- **THEN** no `done` event is written
- **AND** the turn's outcome is `failed`, carrying what the gate observed

#### Scenario: The gate passes and done is written

- **WHEN** the agent proposes `done` with the required effects and the gate passes
- **THEN** the `done` event is appended and the turn's outcome is `advanced`

### Requirement: An item is claimed before any agent runs

A turn SHALL commit its claim of an item before invoking an agent against it, so that an item being
worked on is visible to any other observer of the repository, and so that a turn that dies mid-work
is distinguishable from one that never started.

#### Scenario: The claim is committed before the agent starts

- **WHEN** a turn selects an item to act on
- **THEN** the claim is recorded and committed
- **AND** only then is the agent invoked

#### Scenario: A crash after claiming leaves a legible state

- **WHEN** a turn dies after committing its claim and before recording an outcome
- **THEN** the repository shows the item claimed, by whom, and at which attempt

### Requirement: Concurrency is safe on one machine and fails loudly across machines

A turn SHALL hold a queue lock for the duration of picking and claiming an item, so two turns
reading one queue cannot both claim the same item. A turn SHALL separately hold a workspace lock,
keyed by the workspace's own identity rather than by which queue dispatched the turn, for the
duration of running the agent and committing its effects — so two turns whose workspace resolves to
the same location cannot both execute there, regardless of which queue dispatched either of them.

When a turn's queue and workspace are the same location, both locks SHALL be satisfied by holding
the tree's single-flight lock once, preserving today's single-repository behaviour exactly.

Cross-machine mutual exclusion requires a compare-and-swap push of the claim, which this capability
does not perform. A turn SHALL refuse to run when it is configured for cross-machine operation
without that push, rather than running unprotected.

#### Scenario: A second turn on the same machine does not start

- **WHEN** a turn is running and another turn is invoked with the same queue and the same workspace
- **THEN** the second turn does not start work, and says the queue and workspace are already in use

#### Scenario: A second turn against the same queue does not claim the same item

- **WHEN** a turn is picking and claiming an item and another turn against the same queue starts
- **THEN** the second turn does not claim the item the first is claiming

#### Scenario: A second turn against the same workspace does not execute concurrently

- **WHEN** a turn is executing its agent and committing against a workspace, and another turn —
  regardless of which queue dispatched it — resolves to the same workspace
- **THEN** the second turn does not start executing against that workspace until the first releases it

#### Scenario: Different queues targeting the same workspace still serialize

- **WHEN** two turns dispatched from two different queues both resolve to the same workspace
- **THEN** they do not execute against that workspace concurrently

#### Scenario: Cross-machine operation without compare-and-swap is refused

- **WHEN** a turn is configured to coordinate with other machines but the compare-and-swap push is
  not enabled
- **THEN** the turn refuses to run and names the missing protection

### Requirement: Every turn writes exactly one turn record, and the turn writes it

A turn SHALL write exactly one turn record, for every outcome including the ones where no agent ran
and the ones where the agent failed. The turn — not the process supervisor, and not the agent —
SHALL be the writer of that record.

The record SHALL identify the item the turn acted on, where there was one.

#### Scenario: One record per turn, whatever happened

- **WHEN** any turn ends, by success, refusal, failure, or nothing being ready
- **THEN** exactly one turn record exists for that turn

#### Scenario: A turn that dies leaves a gap rather than a silence

- **WHEN** a turn declares itself and then dies before recording an outcome
- **THEN** the stream shows a position for that turn with no record
- **AND** a reader treats that position as `failed` rather than as a turn that never happened

#### Scenario: The record names the item

- **WHEN** a turn acted on an item
- **THEN** the record identifies that item

### Requirement: A turn commits only the paths it wrote

A turn SHALL commit by naming explicitly the paths it wrote, and SHALL NOT commit by staging
directories or by committing whatever the index happens to hold.

#### Scenario: Unrelated modifications are not swept into the turn's commit

- **WHEN** a turn commits while unrelated files are modified or staged in the same tree
- **THEN** the turn's commit contains only the paths the turn wrote

