# run-guardrails/turn-record Specification

## Purpose
Defines the durable record every run of the factory leaves behind, and the small frozen
vocabulary — a four-value outcome enum — that makes those records comparable to each other
months apart. Everything else in run-guardrails reads this record and nothing else.
## Requirements
### Requirement: The outcome enum is exactly four values

Every turn record SHALL carry an `outcome` field whose value is exactly one of
`advanced`, `blocked`, `nothing-ready`, `failed`. No other value is valid, and the field
is never absent from a well-formed record.

The four values mean:

| Value | Meaning |
|---|---|
| `advanced` | the run moved real work forward — the only value that counts as output |
| `blocked` | the run could not proceed on something external |
| `nothing-ready` | the run found no work eligible to do |
| `failed` | the run broke, or could not deliver a verdict at all |

#### Scenario: A record carrying an unknown outcome is rejected
- **WHEN** a turn record is written with an `outcome` outside the four values
- **THEN** the write is rejected with an error naming the offending value
- **AND** no record is appended to the stream

#### Scenario: A record with no outcome is rejected
- **WHEN** a turn record is written with the `outcome` field missing or empty
- **THEN** the write is rejected
- **AND** no record is appended to the stream

### Requirement: `nothing-ready` is never success

No component SHALL treat `nothing-ready` as evidence of a healthy run, count it toward
progress, or report it as success to any caller or exit code that means success.

**Reason, carried with the rule:** the predicted failure of this system is a long run of
green turns with zero output. A component that reads `nothing-ready` as "fine" cannot
distinguish an idle factory from a broken one, and that is precisely the failure this
capability exists to catch.

#### Scenario: An unbroken run of nothing-ready is not health
- **WHEN** every record in the stream carries `nothing-ready` and none carries `failed`
- **THEN** no consumer reports the stream as healthy on that basis alone

### Requirement: Two writers, and the record says which

A turn record MAY be authored either by the agent that performed the run or by the
supervisor that governed it. Every record SHALL carry `enforced_by` with the value `agent`
or `harness` identifying its author.

The supervisor SHALL author a record whenever the agent cannot: a wall-clock or
turn-ceiling stop terminates the agent process, so the terminated process writes nothing.
A supervisor-authored record for such a stop SHALL carry `outcome: failed` and
`enforced_by: harness`.

**Authoring is not persisting.** The supervisor SHALL return the record it authored and
SHALL NOT append it to the stream unless the caller supplies somewhere to put it. Exactly
one component SHALL write the row for a turn, and it is the component that knows the turn
happened — a supervisor governs one invocation, and a turn may contain none.

**Reason, carried with the rule:** without `enforced_by`, a run killed by the harness is
indistinguishable from a run that failed honestly, and the two demand different responses.
And a turn that finds nothing eligible starts no process at all, so a supervisor that never
ran cannot write the `nothing-ready` row that turn still owes — the row this capability most
needs, because it is what distinguishes an idle factory from a stalled one. A supervisor
that wrote its own row as well would not merely duplicate: the two rows answer different
questions, one about a process and one about a turn.

#### Scenario: A harness kill still produces a record
- **WHEN** the supervisor terminates an agent for exceeding its wall clock
- **AND** the caller supplied somewhere for the record to go
- **THEN** a record is appended carrying `outcome: failed` and `enforced_by: harness`

#### Scenario: An agent verdict is marked as its own
- **WHEN** an agent completes and writes its own verdict
- **THEN** the record carries `enforced_by: agent`

#### Scenario: A governed run with nowhere to write leaves the stream untouched
- **WHEN** a caller governs a run without supplying anywhere to record it
- **THEN** the authored record is returned to the caller
- **AND** no marker and no record appear in the stream

#### Scenario: A turn that runs no agent still owes its row
- **WHEN** a turn finds nothing eligible and starts no process
- **THEN** a record carrying `outcome: nothing-ready` is written for that turn

### Requirement: Every record reports whether the tree was left dirty

Every turn record SHALL carry a boolean `dirty` field stating whether the working tree
held uncommitted modifications when the run ended.

**Reason, carried with the rule:** a harness stop is a kill mid-edit. Without `dirty`, a
torn workspace reads as a clean one on the next turn, and the next run builds on a state
nobody inspected.

#### Scenario: A kill mid-edit is recorded as dirty
- **WHEN** a run is terminated while the working tree holds uncommitted modifications
- **THEN** the appended record carries `dirty: true`

### Requirement: Every record reports the isolation posture it ran under

Every turn record SHALL carry a boolean `isolated` field stating whether the run executed
under the isolated posture or under an explicit opt-out.

#### Scenario: An opt-out is visible in the record
- **WHEN** a run executes with isolation explicitly disabled
- **THEN** the appended record carries `isolated: false`

### Requirement: Turn records are a separate append-only stream

Turn records SHALL be written to their own append-only stream, distinct from the
pre-existing hand-authored ledger rows. Records are never modified and never deleted once
written.

The pre-existing rows are outside this capability by construction — they are a different
stream — and SHALL NOT be migrated, rewritten, or handled by a compatibility branch in
any consumer.

**Reason, carried with the rule:** the existing rows carry free-text outcomes that predate
this enum. A special case that coerces them is a thing a later reader deletes without
knowing why it was there; a separate stream cannot be deleted by accident.

#### Scenario: Existing ledger rows are untouched
- **WHEN** the turn-record stream is created and written to
- **THEN** no pre-existing ledger row is modified, moved, or deleted

#### Scenario: Records are append-only
- **WHEN** a caller attempts to modify or remove a record already in the stream
- **THEN** the attempt is rejected

### Requirement: Records carry no secrets and no host identity

No turn record SHALL contain a credential, an authentication token, or an absolute path
that identifies the operator's machine or home directory.

**Reason, carried with the rule:** this repository is public and the stream is committed.

#### Scenario: Home directory paths never reach the record
- **WHEN** a record is written by a run whose environment includes a home-directory path
- **THEN** the record contains no absolute home-directory path

### Requirement: Why a turn failed is a second axis, not a wider outcome

Every turn record MAY carry a `failure_kind` field naming why the turn failed. It SHALL be absent
or null unless `outcome` is `failed`, and a record carrying a `failure_kind` alongside any other
outcome SHALL be rejected at write time.

**Two axes, one record.** `outcome` answers *did the turn advance* and is exactly four values,
frozen, because every row ever written is compared against every other row. `failure_kind` answers
*why did it fail*, and is **executor-facing and expected to change** as vendors and harnesses
change. Widening `outcome` to carry the reason would conflate the two questions and break the
four-value contract that governing decisions are typed against.

`failure_kind` SHALL be drawn from a closed set, and that set is the union of the executor's two
failing vocabularies flattened onto the single question *why*:

| `failure_kind` | Source |
|---|---|
| `budget_exhausted` | the executor stopped for want of budget |
| `turn_limit` | the executor hit its turn ceiling |
| `cancelled` | the run was cancelled |
| `auth` | the model refused the credentials |
| `rate_limit` | the model was reachable but the quota was not available |
| `crash` | the executor died |
| `bad_output` | the executor produced output the reader could not use |
| `task_error` | the work itself errored |
| `version_mismatch` | the executor and the harness disagreed on version |

The two vocabularies are disjoint in their names, so the flattening is unambiguous and a reader
never has to know which level a value came from.

`failure_kind` MAY be null even when `outcome` is `failed`: a supervisor authoring a record for a
process it killed has no executor reason to report, and `enforced_by: harness` already says who
ended the run. A null `failure_kind` SHALL NOT be read as "no reason exists" — only as "the writer
had no typed reason to give".

**Reason, carried with the rule:** `rate_limit` SHALL be distinguishable from every other failure
and SHALL NOT be folded into a generic failure ([[architecture.md]] §7b rule 3). The model draws
from the same rolling window as the operator's own interactive use, so a factory **starved** of
quota and a factory whose model is **broken** are different conditions demanding different
responses — one waits, the other is fixed. Free text in `note` cannot be queried, so a stall
detector reading only `outcome` and `note` cannot tell them apart.

#### Scenario: A starved run is distinguishable from a broken one

- **WHEN** one run fails because the quota window is exhausted and another fails because the
  executor crashed
- **THEN** both records carry `outcome: failed`
- **AND** the first carries `failure_kind: rate_limit` and the second `failure_kind: crash`
- **AND** a consumer separates them without reading free text

#### Scenario: A failure kind on a non-failed outcome is rejected

- **WHEN** a record is written with `outcome: advanced` and a `failure_kind`
- **THEN** the write is rejected with an error naming both fields
- **AND** no record is appended to the stream

#### Scenario: A kind outside the closed set is rejected

- **WHEN** a record is written with a `failure_kind` outside the closed set
- **THEN** the write is rejected with an error naming the offending value and the valid ones

#### Scenario: A harness kill needs no failure kind

- **WHEN** the supervisor authors a record for a process it terminated
- **THEN** the record carries `outcome: failed` and `enforced_by: harness`
- **AND** a null or absent `failure_kind` is well-formed

#### Scenario: A record written before the field is still readable

- **WHEN** a record with no `failure_kind` key is read
- **THEN** it is rebuilt with `failure_kind` null and no error

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

### Requirement: A writer that knows why a turn failed records it as a typed reason

Where the writer of a record knows why the turn failed, it SHALL record that reason in the
record's typed reason field. It SHALL NOT narrate the reason in the record's free-text note
while leaving the typed field null.

Null SHALL remain legal, and SHALL continue to mean **the writer had no reason to give** —
never that no reason exists. What this requirement forbids is a writer that has the reason
and declines to type it.

**Reason, carried with the rule:** a typed field that no writer populates is indistinguishable
from a field that does not exist. Every consumer of the stream reads the type; free text is
read by a human, once, if at all. A reason narrated into a note is a reason that was known and
then discarded at the moment it became durable.

#### Scenario: A known reason is typed, not narrated
- **WHEN** a record is written for a turn whose failure reason is known
- **THEN** the record's typed reason field carries that reason

#### Scenario: An unknown reason stays null
- **WHEN** a record is written by a writer that does not know why the turn failed
- **THEN** the typed reason field is null and the record is well-formed

#### Scenario: The reason is not duplicated into free text as its only home
- **WHEN** a record carries a reason in its note
- **THEN** the typed field carries it as well

### Requirement: The reason is taken from what the executor reported

The recorded reason SHALL be derived from what the executor reported about the run. It SHALL
NOT be inferred from an exit status, from an error string, or from the shape of the record
stream, where the executor states it natively.

**Reason, carried with the rule:** the distinction this field exists to preserve — a starved
factory against a broken one — is reported by the executor rather than deduced. A deduction
that agrees with the report adds nothing; one that disagrees is a fabrication in a durable
row, and the row outlives everything that could correct it.

#### Scenario: A reported reason is recorded as reported
- **WHEN** the executor states the reason for a run ending
- **THEN** the recorded reason is that reason

#### Scenario: No reason is invented where none was reported
- **WHEN** the executor reports no reason
- **THEN** the recorded reason is null

### Requirement: A harness stop records the reason the harness knows

Where the harness itself stops a run because a configured bound was exceeded, and the union
contains a value naming that bound, the record SHALL carry that value. Where the union
contains no value naming the bound, the reason SHALL be null and the note SHALL say which
bound fired.

**Reason, carried with the rule:** the harness's own stops are the failures most likely to
recur, and a stop the harness chose is the one case where the writer certainly knows why.
Leaving them null makes the most repeatable failures the least legible ones in the stream.

#### Scenario: A turn-ceiling stop is typed
- **WHEN** the harness stops a run for exceeding its turn ceiling
- **THEN** the record carries the reason naming that bound

#### Scenario: A bound with no value in the union is not invented
- **WHEN** the harness stops a run for exceeding a bound the union does not name
- **THEN** the reason is null and the note names the bound that fired

#### Scenario: A harness stop is still the harness's ending
- **WHEN** the harness stops a run and records a reason for it
- **THEN** the record still attributes the ending to the harness rather than the agent

