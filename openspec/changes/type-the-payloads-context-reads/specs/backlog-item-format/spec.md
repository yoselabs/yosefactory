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
| `gate_rejected` | `doing` | unchanged | `report`, `attempt` |
| `blocked` | `claimed`, `doing` | `blocked` | `awaiting` |
| `unblocked` | `blocked` | the stored `awaiting.return_to` | `resolution` (`qid`, `by`, and `answer` when the resolution was an answered question) |
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

Some carried fields SHALL additionally declare a required type, not only required presence. Where
declared, a present field whose value does not match its declared type SHALL fail the read the same
way a missing required field or a pattern mismatch does — naming the field, the value, and the
expected type(s). `unblocked`'s `resolution` is declared as either a string (the deadline-timeout
case) or a mapping (the answer case): both are legal shapes for the same field, and only a third
shape is rejected.

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

#### Scenario: A payload field with the wrong declared type fails the read

- **WHEN** a `failed` event carries `retryable: "true"` — a string, where the declared type is
  `bool`
- **THEN** reading the item fails and names the field, the value, and the expected type
- **AND** the same posture applies to any other event whose carried field has a declared type, the
  same way a malformed `on_timeout` fails wherever it appears
