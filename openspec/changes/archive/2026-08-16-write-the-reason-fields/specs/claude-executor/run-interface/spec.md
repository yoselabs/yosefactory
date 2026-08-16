## MODIFIED Requirements

### Requirement: The executor outcome vocabulary is separate from the turn outcome

An executor result SHALL carry an outcome answering *what the executor did*, distinct from the
turn outcome answering *did the turn advance*. The executor vocabulary SHALL distinguish at
least: success, budget exhaustion, turn-limit stop, an approval the agent was denied, a
refusal, a cancellation, and failure.

The mapping from the executor vocabulary down to the turn outcome SHALL be total and declared
in one place. **The component that writes a turn record from an executor result SHALL obtain the
turn outcome from that mapping, and SHALL NOT assert an outcome of its own.** A declared mapping
that the record-writing path bypasses is not a mapping; it is documentation of one.

**Reason, carried with the rule:** the turn outcome is frozen because every row ever written is
compared against every other one. The executor vocabulary changes when vendors change. Merging
them would either freeze the soft one or thaw the frozen one.

**Second reason, added on the receipt that the first was insufficient:** the mapping was total and
declared and the only production caller ignored it, narrowing every non-success ending to `failed`.
Two of the seven endings — an approval denied, and a refusal — therefore could not be recorded as
what they were, and the record said the run had broken when it had stopped. *Totality is a property
of the mapping; using it is a property of the caller, and only the second one is observable in a
row.* This requirement was satisfied throughout, which is the point: a contract checkable against the
mapping alone cannot see its only caller ignoring it.

**The operator consequence, which is why this is a defect and not a tidiness matter:** a row reading
`failed` for a run the model correctly declined tells whoever reads it to go and debug a model that
behaved properly. That is the same discriminator error as quota exhaustion arriving as a task error,
one layer up — the wrong fix applied to a healthy component, at the cost of the time it takes to find
nothing wrong.

#### Scenario: Every executor outcome maps to a turn outcome
- **WHEN** an executor produces any outcome in its vocabulary
- **THEN** a turn outcome is derivable from it without a caller-side branch

#### Scenario: The executor never claims there was nothing to do
- **WHEN** an executor produces a result
- **THEN** its outcome is never `nothing-ready`, which is a judgement about the backlog made before any executor is started

#### Scenario: A denied approval is not recorded as a failure

- **WHEN** a run ends because the agent was denied a tool it asked for
- **THEN** the turn record's outcome is the one the declared mapping gives for that ending
- **AND** it is not `failed`

#### Scenario: The record-writing path takes the outcome from the mapping

- **WHEN** a turn record is written from an executor result
- **THEN** its outcome is the mapping's image of the result's outcome
- **AND** no branch in the writing path substitutes a different one

### Requirement: Quota exhaustion is never reported as a broken model

Exhausted quota SHALL be carried as its own failure kind, distinguishable in the result from a
task error, a crash, or malformed output.

A result SHALL carry the failure kind on a separate axis from the outcome, and that kind SHALL
reach the turn record **as the record's own typed field**. It SHALL NOT be carried into the record
as prose, in a note, or in any other free-text form: a stall detector cannot query free text, which
is the whole reason the kind is typed.

**Reason, carried with the rule:** a factory starved of quota that reads as a broken model gets
the wrong fix applied to it, and the wrong fix is expensive.

**On the retired clause:** this requirement previously said the kind must reach the record *until* a
record could hold it as a typed field. A record now can, so the interim ends and the weaker form is
gone rather than left standing as an alternative a later writer could satisfy instead.

#### Scenario: A rate-limited run is distinguishable afterwards
- **WHEN** a run fails because quota was exhausted
- **THEN** the result names the failure kind as rate limiting, separately from its outcome

#### Scenario: The kind survives the narrowing to a record
- **WHEN** an executor result is narrowed to a turn record
- **THEN** the failure kind is still recoverable from that record

#### Scenario: The kind reaches the record as a field, not as prose

- **WHEN** an executor result carrying a failure kind is narrowed to a turn record
- **THEN** the record's typed failure-kind field holds it
- **AND** a consumer reads it without parsing any human-readable text
