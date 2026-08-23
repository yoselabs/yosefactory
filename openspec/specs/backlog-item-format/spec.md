# backlog-item-format Specification

## Purpose
The on-disk representation of a work item: an append-only log of events whose fold is the item's current state, so that concurrent writers never conflict and no closed item is ever rewritten to make a later one readable.
## Requirements
### Requirement: One append-only log per item

Each work item SHALL be stored as exactly one file, `backlog/items/<id>.jsonl`, containing one JSON object per line. Writers SHALL only append. No line is ever edited, reordered in place, or removed ([[D002]]).

An item id SHALL match `[a-z0-9][a-z0-9._-]*` and SHALL be stable for the life of the item.

#### Scenario: Two writers touch two items

- **WHEN** one writer appends to `backlog/items/a.jsonl` and another appends to `backlog/items/b.jsonl`
- **THEN** neither write can conflict with the other, because no file is shared

#### Scenario: A closed item is never rewritten

- **WHEN** an item reaches a terminal state and a later item is created from it
- **THEN** the terminal item's file is unchanged from the moment it closed
- **AND** every line written before closing is byte-identical to what it was when written

### Requirement: Event record shape

Every line SHALL be a JSON object carrying at least:

- `event_id` — unique within the item; the idempotency key for that event
- `ts` — RFC3339 timestamp with an explicit UTC offset
- `actor` — who wrote it
- `event` — one of the event names defined by this capability

Event-specific payload fields SHALL appear as siblings, not nested under a generic envelope. A line that is not valid JSON, or lacks any of the four required fields, SHALL be an error that fails the read.

#### Scenario: A malformed line is not skipped

- **WHEN** a log contains a line that is not valid JSON
- **THEN** reading the item fails and names the file and line number
- **AND** no partial state is returned

#### Scenario: A duplicated event is applied once

- **WHEN** the same `event_id` appears on two lines of the same item's log
- **THEN** the fold applies it exactly once
- **AND** reading the item succeeds

### Requirement: Current state is the fold of the trail

An item SHALL NOT store its current state, lease, awaiting block, successor, survivor, priority or frame as a rewritable field. All of them SHALL be derived by replaying the item's events ([[architecture.md §4]]).

Replay order SHALL be deterministic and independent of the order lines happen to sit in the file, since a merge may interleave them: events SHALL be ordered by `ts`, ties broken by `event_id` compared as a string.

#### Scenario: State survives a merge that interleaves lines

- **WHEN** the same set of event lines is read in two different file orders
- **THEN** the derived state is identical in both cases

### Requirement: Thirteen states and a terminal predicate

An item SHALL at all times be in exactly one of: `ready`, `claimed`, `doing`, `blocked`, `falsified`, `failed`, `done`, `cancelled`, `duplicate`, `needs_split`, `snoozed`, `poison`, `abandoned`.

`terminal` SHALL be a derived predicate, not a state: an item is terminal when its state is one of `done`, `cancelled`, `poison`, `duplicate`, `abandoned` ([[architecture.md §3]]).

No event SHALL be accepted against an item that is already terminal, except `note`.

#### Scenario: Terminal is derived, never written

- **WHEN** an item's log ends with a `done` event
- **THEN** its state is `done` and its terminal predicate is true
- **AND** no event named `terminal` exists in the vocabulary

#### Scenario: Writing after close is rejected

- **WHEN** a `claimed` event is appended to an item whose state is `cancelled`
- **THEN** reading the item reports an illegal transition and names both states

### Requirement: The event vocabulary and its transitions

The following events SHALL be defined, and each SHALL be legal only from the listed states:

| Event | From | To | Carries |
|---|---|---|---|
| `created` | — | `ready` | `loop`, `frame` |
| `priority_set` | any non-terminal | unchanged | `priority` |
| `frame_amended` | any non-terminal | unchanged | the changed frame keys only |
| `claimed` | `ready` | `claimed` | `owner`, `expires_at`, `attempt` |
| `started` | `claimed` | `doing` | — |
| `released` | `claimed`, `doing` | `ready` | `owner`, `reason` |
| `reclaimed` | `claimed`, `doing` | `ready` | `reason`, `expired_owner`, `expired_attempt` |
| `gate_rejected` | `doing` | unchanged | `report`, `attempt` |
| `blocked` | `claimed`, `doing` | `blocked` | `awaiting` |
| `unblocked` | `blocked` | the stored `awaiting.return_to` | `resolution`, `ref` |
| `snoozed` | `ready`, `blocked` | `snoozed` | `scheduled_for` |
| `woke` | `snoozed` | `ready` | `cause` |
| `falsified` | `doing` | `falsified` | `by`, `successor` |
| `failed` | `claimed`, `doing` | `failed` | `reason`, `attempt`, `retryable` |
| `needs_split` | `doing` | `needs_split` | `children` |
| `done` | `doing` | `done` | `effects`, `verified_by` |
| `cancelled` | any non-terminal | `cancelled` | `reason` |
| `duplicate` | any non-terminal | `duplicate` | `survivor` |
| `poisoned` | `failed` | `poison` | `attempts` |
| `abandoned` | any non-terminal | `abandoned` | `reason` |
| `note` | any | unchanged | `body` |

An event that is legal from no state, or whose `event` name is not in this table, SHALL fail the read
rather than be skipped. Forward compatibility is deliberately not offered: a reader that silently
ignores an event it does not understand reports a state that never existed.

#### Scenario: An unknown event fails loudly

- **WHEN** a log contains an event named `archived`, which is not in the vocabulary
- **THEN** reading the item fails and names the unknown event
- **AND** the item's state is not reported as if that line were absent

#### Scenario: A failure is not a falsification

- **WHEN** a turn ends because an API call returned HTTP 500
- **THEN** the recorded event is `failed`, not `falsified`
- **AND** no successor is emitted

#### Scenario: A reclaimed item returns to ready, distinguishably from a released one

- **WHEN** a `claimed` or `doing` item is reclaimed
- **THEN** its state folds to `ready`
- **AND** the log names `reason`, the `expired_owner` whose lease lapsed, and the `expired_attempt`
  number — distinct fields from `released`'s `owner`/`reason`, so a reader can tell "the owner gave
  it back" from "the owner's lease expired and something else took it back" without inferring from
  context

#### Scenario: A gate rejection leaves the item in `doing`, not silently unrecorded

- **WHEN** a `done` proposal fails the verification gate on an item that is `doing`
- **THEN** a `gate_rejected` event is appended, carrying the gate's report and the attempt it was
  rejected on
- **AND** the item's state is still `doing` — no state transition occurred
- **AND** the item's log is not silent about the rejection the way it was before this event existed

#### Scenario: An answered question's text lands on the item, not only on the question

- **WHEN** a blocked item's question is answered and `apply_answers()` unblocks it
- **THEN** the `unblocked` event's `resolution` carries the answer's text, not only `qid` and `by`
- **AND** the question's own log still carries the canonical `answered` record — the item's copy is
  read-only and never the thing a later decision is made from

### Requirement: The frame

`created` SHALL carry a `frame` object with `goal`, `method` and `assumptions` ([[D019]]). `goal` and `method` are strings; `assumptions` is a list of strings, possibly empty.

The frame SHALL be amended only by appending a `frame_amended` event carrying the changed keys. The frame at any point is the fold of `created` plus every subsequent `frame_amended`.

#### Scenario: An amended goal keeps its history

- **WHEN** an item is created with one goal and later amended to another
- **THEN** the current frame reports the new goal
- **AND** the original goal is still readable in the `created` line

### Requirement: Falsification emits a successor and loses nothing

A `falsified` event SHALL carry `by` — what falsified the item, in full, not a reference to something outside the log — and `successor`, the id of the item created to carry the work forward ([[D019]]).

The successor's `created` event SHALL carry `predecessor`, the falsified item's id, and SHALL carry the falsification as input to its own frame.

Both links SHALL be written by appending. Neither item's earlier lines are touched.

#### Scenario: The falsified item and its successor round-trip

- **WHEN** an item is falsified and its successor created
- **THEN** the falsified item reads as state `falsified`, with its original frame, its full trail, and `successor` pointing at the new item
- **AND** the successor reads as state `ready`, with `predecessor` pointing back and its frame naming what falsified the predecessor
- **AND** following `successor` forward and `predecessor` back returns to the item started from
- **AND** no field present before the falsification is absent after it

### Requirement: Duplicates name a survivor

A `duplicate` event SHALL carry `survivor`, the id of the item that continues. The duplicate is terminal; the survivor is unaffected and SHALL NOT be modified by the other item closing.

#### Scenario: Closing a duplicate does not touch the survivor

- **WHEN** item `b` is closed as a duplicate of item `a`
- **THEN** `b` is terminal with `survivor: a`
- **AND** `a`'s log has no new line

### Requirement: The backlog directory is self-describing

`backlog/` SHALL contain a `README.md` stating the append-only rule and pointing at this capability's spec, and the worked example demonstrating the falsified→successor round-trip SHALL be committed under `backlog/` as fixtures a reader can inspect without running anything.

#### Scenario: A reader with no Python can check the claim

- **WHEN** someone opens `backlog/` and reads the fixtures
- **THEN** the falsified item, its successor, and the link in both directions are visible as literal lines

### Requirement: Blocked means blocked until, and the until lives wherever it has a home

A `blocked` event SHALL carry an `awaiting` object with:

- `kind` — one of `question`, `request`, `item`
- `ref` — what is awaited; for `kind: item` this is another item's id, and for `kind: question` or
  `kind: request` it is the `qid` of the question that owns the block's closure
- `who` — the party that owes an answer
- `since` — RFC3339
- `return_to` — the state the item returns to when unblocked, **stored at block time and never
  recomputed** ([[architecture.md §5]])
- `nudge_at` — a list of RFC3339 timestamps, possibly empty

Whether the block carries its own `deadline` and `on_timeout` depends on whether those fields have
another home:

| `kind` | `deadline` / `on_timeout` | Why |
|---|---|---|
| `question`, `request` | SHALL NOT be repeated on the item | the question carries them; a second copy is two representations of one fact, and the copy that drifts decides whether the item starves |
| `item` | SHALL be carried on the `awaiting` block | there is no question, so no other record can carry them — and a block with no bound anywhere can hang forever |

**The duplication argument applies only where the fact has another home.** For `kind: item` nothing
is duplicated, so removing the fields would remove the only bound that exists and breaks S172 —
every loop must close.

When `on_timeout` is present it SHALL be one of `escalate`, `default:<answer>`, or
`abandon:<reason>`, and a value outside that set SHALL fail the read. Whether the field is
*required* for `kind: item` is enforced by the writer: the requirement is conditional on another
field of the same record, which the declaration cannot express today. Present-but-unenforced is the
deliberate position, and it is strictly better than absent.

`unblocked` SHALL move the item to the `return_to` recorded on the `blocked` event it resolves,
whether it was resolved by an answer or by the deadline firing.

#### Scenario: A question-kind block carries no deadline of its own

- **WHEN** a `blocked` event carries an `awaiting` object with `kind: question` and a `ref`, and no
  `deadline` or `on_timeout`
- **THEN** the item reads normally and folds to `blocked`
- **AND** the closure that bounds the block is read from the question named by `ref`

#### Scenario: An item-kind block carries its own deadline

- **WHEN** a `blocked` event carries an `awaiting` object with `kind: item`, a `deadline`, and an
  `on_timeout`
- **THEN** the item reads normally and folds to `blocked`
- **AND** those fields are the bound on the block, because no question exists to hold them

#### Scenario: One deadline, in one place

- **WHEN** the deadline of an item blocked on a question is needed
- **THEN** it is read from the question named by `ref`
- **AND** the item's log holds no `deadline` that could disagree with it

#### Scenario: A malformed on_timeout still fails wherever it appears

- **WHEN** an `awaiting` block carries `on_timeout: wait`
- **THEN** the read fails, naming the field and the value, whatever the block's `kind`

#### Scenario: The deadline fires

- **WHEN** an item is blocked on a question whose `on_timeout` is `escalate`, and that deadline
  passes with no answer
- **THEN** the resolution is recorded as an `unblocked` event with `resolution: timeout`
- **AND** the item returns to the `return_to` stored when it blocked, not to a recomputed state

#### Scenario: An answer arrives before the deadline

- **WHEN** an item blocked until a future deadline receives an answer now
- **THEN** it unblocks now rather than waiting for the deadline

### Requirement: A lease is reclaimable, and reclaiming is bounded by the attempt counter

`claimed.expires_at` SHALL be honored: an item whose state is `claimed` or `doing` and whose most
recent lease's `expires_at` has passed SHALL be eligible for the `reclaimed` transition, returning it
to `ready`. Nothing about this requirement specifies *who* performs the reclaim or *when* within a
turn — that is `turn-cycle`'s concern — only that the state machine offers the transition and that it
is legal exactly where a stale claim exists.

The same `attempt` counter `claimed` already carries (incremented on every claim, D002-append-only —
never reset, never rewritten) SHALL gate how many times an item may be reclaimed before it is
poisoned instead: once the most recent lease's `attempt` reaches a configured ceiling, the item SHALL
instead receive a `failed` event (`retryable: false`, naming the exhausted lease) followed by
`poisoned`, rather than another `reclaimed`.

`failed.retryable`, required by this format since it was defined and previously read by no code
anywhere in `src/`, SHALL be honored the same way: a `failed` event carrying `retryable: false`
SHALL make the item eligible for immediate `poisoned`, regardless of its `attempt` count.

**Reason, carried with the rule:** before this requirement, `expires_at` was written and read by
nothing (`git grep expires_at` found the declaration, `backlog.lease()`, and the writer, and no
consumer) — a turn that died after `claimed`/`started` parked its item in `doing` permanently, with
no route back, identical in effect to an unrecoverable `failed`. Reclaiming without a cap would trade
a permanent freeze for a permanent retry storm on any item that reliably kills the process that
claims it; the cap makes the failure visible (poisoned, terminal, named) instead of either.

#### Scenario: An expired lease is reclaimed

- **WHEN** an item is `claimed` or `doing`, its lease's `expires_at` is in the past, and its most
  recent `attempt` is below the configured ceiling
- **THEN** a `reclaimed` event returns it to `ready`
- **AND** it is eligible for a new claim

#### Scenario: A lease that keeps expiring is poisoned, not reclaimed forever

- **WHEN** an item's lease has expired and its most recent `attempt` has reached the configured
  ceiling
- **THEN** a `failed` event is appended (`retryable: false`), followed by `poisoned`
- **AND** the item is terminal and is never claimed again

#### Scenario: A non-retryable failure is poisoned immediately

- **WHEN** an agent proposes a `failed` event carrying `retryable: false`
- **THEN** the item is poisoned in the same turn, regardless of how many attempts it has had

#### Scenario: An unexpired lease is not reclaimed

- **WHEN** an item is `claimed` or `doing` and its lease's `expires_at` is still in the future
- **THEN** no `reclaimed` event is legal against it yet

#### Scenario: The attempt count survives a return to `ready`

- **WHEN** an item is claimed, released or reclaimed back to `ready`, and claimed again
- **THEN** the number of attempts counted for the exhaustion ceiling reflects every `claimed` event
  the item's log has ever carried, not only the lease currently in force
- **AND** this holds however many times the item has cycled back through `ready`, since `ready`
  itself carries no lease for a later read to find

### Requirement: `gate_rejected` never resets or reclassifies the item

`gate_rejected` SHALL NOT change the item's state and SHALL NOT be confused with `failed`: it does
not consume the item's attempt budget in the sense `failed`/`poisoned` do, and it is not eligible for
`poisoned` on its own. An item may carry any number of `gate_rejected` records while remaining
`doing`.

**A `doing` item whose most recent event is `gate_rejected` is eligible for the scheduler's fast
path**: it may be acted on again directly, without a `released`/`reclaimed` trip through `ready` and
without a new `claimed` event, for as long as its existing lease has not expired. This is the
transition-level guarantee `turn-cycle`'s "Classification is derived from state, never declared"
reads to admit such an item into `eligible()`.

#### Scenario: Repeated gate rejections do not poison the item

- **WHEN** an item accumulates several `gate_rejected` events across retried attempts
- **THEN** its state remains `doing` throughout
- **AND** no `poisoned` event is triggered by `gate_rejected` events alone

#### Scenario: A gate-rejected item is acted on again without a new claim

- **WHEN** an item is `doing`, its most recent event is `gate_rejected`, and its lease has not
  expired
- **THEN** it may be acted on again without any `released`, `reclaimed`, or `claimed` event
  appearing between the `gate_rejected` record and the next record the new attempt appends
- **AND** the item's `attempt` count — read from its most recent `claimed` event — is unchanged

