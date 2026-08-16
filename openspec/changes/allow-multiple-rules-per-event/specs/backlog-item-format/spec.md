## ADDED Requirements

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

## REMOVED Requirements

### Requirement: Blocked means blocked until

**Reason**: The `awaiting` block required `deadline` and `on_timeout` unconditionally, including
for `kind: question` and `kind: request`, where the question already carries them — two
representations of one fact. Replaced by "Blocked means blocked until, and the until lives wherever
it has a home", which keeps every field and every scenario except the one asserting that a block
without a `deadline` fails the read. That assertion cannot survive: the fields are now required of
one `kind` and forbidden to another, and a requirement conditional on a sibling field of the same
record is not expressible in the declaration the fold reads.

**Migration**: No stored data migrates — no committed item log carries a `blocked` event (verified,
tasks 1.1). A writer blocking on a question stops emitting `deadline` and `on_timeout` and names
the question in `ref`; a writer blocking on another item keeps emitting them. Item logs written
before this change stay readable, because the fields are tolerated rather than forbidden.
