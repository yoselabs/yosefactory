# claude-executor/run-interface Specification

## Purpose
The one caller-facing surface every executor lane implements, so that a job gets its budget
honoured and a structured outcome back without naming, or branching on, the agent binary
underneath it.
## Requirements
### Requirement: One bounded call is the whole caller-facing surface

An executor SHALL expose a single operation that takes the work's frame, the working tree it
may edit, and the limits it must respect, and returns a structured result describing what the
invocation amounted to.

The operation SHALL be bounded: it returns, or the run is stopped and it returns anyway. It
SHALL NOT require the caller to poll, resume, or reconnect to a run it started.

A check that a given callable's signature matches this requirement SHALL run unconditionally —
gated on neither the real agent binary's presence on `PATH` nor its version. Such a check
inspects a Python callable's signature; it performs no invocation and asserts nothing about the
binary's behaviour, so gating it behind a live-binary guard only hides a real drift in the
signature itself.

**Reason, carried with the rule:** `test_the_wrapper_matches_the_executor_protocol` was gated
behind the same version-pinned `skipif` as the tests that do drive a real binary, purely because
it lived in the same file. The assertion went stale across two changes (`context`, then
`transcripts_dir`) and nobody noticed, because the gate that made sense for its neighbours also
silenced it. A protocol-conformance check has nothing in common with a behavioural receipt against
a real binary; conflating their gating conflates their risk.

#### Scenario: A run returns a structured result rather than output
- **WHEN** a caller invokes an executor with a frame, a working tree and limits
- **THEN** it receives a result carrying an outcome, usage, the transcript location, and whether the tree was left dirty

#### Scenario: A stopped run still returns
- **WHEN** a run is stopped because it exceeded a limit
- **THEN** the call returns a result rather than raising or hanging

#### Scenario: The protocol-conformance check runs with no `claude` binary present
- **WHEN** `make check` (or plain `pytest`, with no `-m live`) runs on a machine with no `claude`
  binary on `PATH` at all
- **THEN** the check that a wrapper's call signature matches `Executor.__call__` still runs and
  still asserts, rather than being skipped

#### Scenario: The protocol-conformance check runs on a machine whose installed `claude` has
drifted from the pin
- **WHEN** `claude` is present on `PATH` but `claude --version` reports something other than
  `PINNED_VERSION`
- **THEN** the signature-conformance check still runs (it is not gated on the binary's version at
  all), independent of whichever tests in the same file *are* gated on it

### Requirement: The caller is capability-blind

The caller SHALL NOT branch on what the underlying binary can do. Every difference between
lanes SHALL be absorbed by the executor, which either honours the caller's limits itself or
reports that it could not.

**Reason, carried with the rule:** the point of one interface is that a second lane is a
configuration change and not a caller change. A caller that asks "which executor is this" has
already broken the property the interface exists to provide.

#### Scenario: No capability check reaches the caller
- **WHEN** a caller invokes any executor lane
- **THEN** the call site is identical regardless of which lane is configured

#### Scenario: An unhonourable limit is reported, not silently dropped
- **WHEN** an executor cannot enforce a limit the caller supplied
- **THEN** the result reports the failure rather than returning as though the limit applied

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

### Requirement: A result reports the tree it left behind

Every executor result SHALL report whether the working tree was left with uncommitted
modifications by the agent.

The harness's own evidence — the transcript, run markers, and anything else written by the
harness rather than by the agent — SHALL NOT make a tree read as dirty.

#### Scenario: An agent that stopped mid-edit reads as dirty
- **WHEN** a run is stopped while the agent had uncommitted modifications in the tree
- **THEN** the result reports the tree as dirty

#### Scenario: The observer does not appear in what it observes
- **WHEN** a run completes having written only its own transcript and run markers
- **THEN** the result reports the tree as clean

