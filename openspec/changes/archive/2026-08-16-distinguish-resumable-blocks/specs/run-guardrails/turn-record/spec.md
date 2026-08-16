## ADDED Requirements

### Requirement: Why a turn is blocked is a second axis, and resumability is derived from it

Every turn record MAY carry a `blocked_kind` field naming why the turn could not proceed. It SHALL
be absent or null unless `outcome` is `blocked`, and a record carrying a `blocked_kind` alongside any
other outcome SHALL be rejected at write time.

This is the same shape as `failure_kind` and for the same reason. `outcome` answers *did the turn
advance* and is exactly four values, frozen. `blocked_kind` answers *what is being waited on*, is
executor-facing, and is expected to change as harnesses change. Widening `outcome` to a fifth value
would break the four-value contract that governing decisions are typed against.

`blocked_kind` SHALL be drawn from a closed set of three values:

| `blocked_kind` | What blocked the turn | Resumable by something arriving |
|---|---|---|
| `awaiting` | the work item entered `blocked`; the block's own `awaiting` object names what is awaited and holds its bound | yes |
| `needs_approval` | the agent was denied a tool it asked for and a human must grant it | yes |
| `refused` | the agent declined the work itself | **no** |

**These three SHALL be values of a field and SHALL NOT become states of the work item.** `blocked` is
a place an item sits; `needs_approval` and `refused` are facts about one executor invocation, and
**nothing would write an item into either.** An agent that declines the work leaves the item exactly
where it was — still `doing` — so a `refused` item state would have no writer, and a state with no
writer means the same fact has two representations that can disagree. This is the argument that keeps
`terminal` a derived predicate rather than a fourteenth state ([[architecture.md §3]]), applied to the
same temptation one level up.

**Resumability SHALL be derived from `blocked_kind` and SHALL NOT be recorded as a field of its
own.** A stored boolean alongside the kind is two representations of one fact, and the copy that
drifts is the one a stall detector reads. Every consumer that needs to know whether a block can
clear SHALL obtain it from one definition rather than reproducing the mapping.

`blocked_kind` MAY be null even when `outcome` is `blocked`, for the same reason `failure_kind` may
be: a writer that has no typed reason to give records none. A null `blocked_kind` SHALL NOT be read
as "the block is resumable" or as "the block is a dead end" — resumability is then unknown, and a
consumer SHALL distinguish unknown from either answer.

**Reason, carried with the rule:** a run of `blocked` records means one of two opposite things. If
the blocks are resumable the factory is waiting and the correct response is to wait; if they are
refusals nothing will ever arrive and the correct response is for a human to re-decide the goal. A
detector that cannot separate them either nags about healthy waiting or stays silent through a dead
factory. Free text in `note` cannot be queried, so the distinction must be typed to be usable.

#### Scenario: A wait is distinguishable from a dead end

- **WHEN** one turn ends blocked because its item is awaiting an answer, and another ends blocked
  because the agent refused the work
- **THEN** both records carry `outcome: blocked`
- **AND** the first carries `blocked_kind: awaiting` and the second `blocked_kind: refused`
- **AND** a consumer separates them without reading free text

#### Scenario: Resumability comes from the kind, not from a second field

- **WHEN** a consumer needs to know whether a blocked record can clear on its own
- **THEN** it derives the answer from `blocked_kind`
- **AND** no turn record carries a stored resumability flag that could disagree with the kind

#### Scenario: A blocked kind on a non-blocked outcome is rejected

- **WHEN** a record is written with `outcome: advanced` and a `blocked_kind`
- **THEN** the write is rejected with an error naming both fields
- **AND** no record is appended to the stream

#### Scenario: A kind outside the closed set is rejected

- **WHEN** a record is read whose `blocked_kind` is a value not in the closed set
- **THEN** the read fails with an error naming the offending value and the valid set

#### Scenario: A record written before the field exists still reads

- **WHEN** a record carrying no `blocked_kind` key at all is read
- **THEN** the read succeeds and reports the kind as null
- **AND** resumability is reported as unknown rather than as either answer

#### Scenario: The two reason axes do not collide

- **WHEN** one record carries `outcome: failed` with a `failure_kind`, and another carries
  `outcome: blocked` with a `blocked_kind`
- **THEN** both are well-formed
- **AND** no record carries both fields, because no record carries both outcomes

### Requirement: Two blocked kinds have no automatic closure, and the record says so

Of the three blocked kinds, only `awaiting` is bounded: the block it describes carries a deadline and
an `on_timeout` policy, either on the question it references or on the block itself, so the loop
closes without a human.

`needs_approval` and `refused` SHALL be documented as having no such bound. Neither has a deadline,
neither has a policy, and nothing sweeps them. A turn that ends in either leaves work that only a
human moves.

**This is declared rather than fixed, and the two cases are not the same defect:**

- `refused` is a dead end **by design.** Nothing arriving changes a refusal; the response is a human
  re-deciding, which is the falsify-and-succeed path rather than a resumption ([[D019]] — a wrong
  method is amended, a wrong goal is closed falsified with a successor). Recording it as a dead end
  is the correct behavior, not a gap.
- `needs_approval` is a dead end **by omission.** It is resumable in principle and unbounded in
  practice, because a permission denial writes no question and so acquires no deadline. This
  violates S172 — every loop must close — and it violated it before this change too; the field makes
  it visible instead of creating it. Bounding it requires the denial to raise a question, which is
  outside this capability.

#### Scenario: An unbounded block is visible as unbounded

- **WHEN** a turn ends with `blocked_kind: needs_approval`
- **THEN** the record identifies a block that no deadline or timeout policy bounds
- **AND** a consumer can identify it as such without inspecting any other file

#### Scenario: A refusal is not reported as a wait

- **WHEN** a consumer summarises a stream containing records with `blocked_kind: refused`
- **THEN** those records are not counted as the factory waiting on something
