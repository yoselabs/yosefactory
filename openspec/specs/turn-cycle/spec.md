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

### Requirement: A turn's spend row is committed in the same commit as its run record

When a turn ran an executor, the turn SHALL write the resulting cost as a spend row and SHALL
include that row's path in the same `commit()` call that stages the turn's own run record. The turn
SHALL NOT write the spend row anywhere the commit that follows cannot reach, and SHALL NOT commit
the run record without attempting to commit the spend row alongside it in the same git operation.

Zero cost is a real value and SHALL still produce a row: absence SHALL NOT be read as "this run
never happened."

**Reason, carried with the rule:** a spend row written to disk but never named in a commit's
pathspec is invisible to `git commit -- <paths>` by construction (Article V) — it survives on disk
until something else happens to sweep it up, and nothing does. A row written to a different
repository than the one the turn commits into is invisible for a stronger reason: no pathspec in any
commit against that repository can ever name it. Both were true before this requirement; a green
`make check`, a pushed run record, and CI's own logs all read as success while the row was silently
lost.

#### Scenario: A turn that spent money commits its spend row alongside its run record

- **WHEN** a turn runs an executor that reports a nonzero cost, and the turn's outcome is recorded
- **THEN** the same commit that carries the turn's run record also carries a spend row naming that
  run's id and cost
- **AND** the spend row is present in `git show HEAD` for that commit, not merely written to disk

#### Scenario: A turn that spent exactly zero still commits a row

- **WHEN** a turn runs an executor that reports zero cost
- **THEN** a spend row for that run's id, carrying zero, is committed alongside the run record
- **AND** a reader of the spend log cannot distinguish "this run cost nothing" from "this run's cost
  was never recorded" by the row's absence, because there is no absence

#### Scenario: A turn that never ran an executor commits no spend row

- **WHEN** a turn ends without ever invoking an executor (nothing eligible and nothing to plan)
- **THEN** no spend row is written or committed for that turn

#### Scenario: A spend-write failure does not cost the turn its run record or the agent's delivered commit

- **WHEN** the spend row fails to write (e.g. the underlying file write raises)
- **THEN** the turn's run record is still written and committed
- **AND** any workspace commit the turn already delivered for a `done` proposal is unaffected
- **AND** the turn's note names the spend-recording failure

#### Scenario: The spend row is written to the repository the turn's commit actually stages

- **WHEN** a turn's queue and the package's own installed location are different directories
- **THEN** the spend row is written inside the queue repository, not resolved from the package's own
  location
- **AND** the commit that stages the run record is able to name and stage the spend row's path,
  because both live in the same repository

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

