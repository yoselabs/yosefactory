## MODIFIED Requirements

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

## ADDED Requirements

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
