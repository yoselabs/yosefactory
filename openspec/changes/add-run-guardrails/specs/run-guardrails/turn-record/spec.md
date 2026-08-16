## Purpose

Defines the durable record every run of the factory leaves behind, and the small frozen
vocabulary — a four-value outcome enum — that makes those records comparable to each other
months apart. Everything else in run-guardrails reads this record and nothing else.

## ADDED Requirements

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

**Reason, carried with the rule:** without `enforced_by`, a run killed by the harness is
indistinguishable from a run that failed honestly, and the two demand different responses.

#### Scenario: A harness kill still produces a record
- **WHEN** the supervisor terminates an agent for exceeding its wall clock
- **THEN** a record is appended carrying `outcome: failed` and `enforced_by: harness`

#### Scenario: An agent verdict is marked as its own
- **WHEN** an agent completes and writes its own verdict
- **THEN** the record carries `enforced_by: agent`

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
