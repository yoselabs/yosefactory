## Purpose

The one caller-facing surface every executor lane implements, so that a job gets its budget
honoured and a structured outcome back without naming, or branching on, the agent binary
underneath it.

## ADDED Requirements

### Requirement: One bounded call is the whole caller-facing surface

An executor SHALL expose a single operation that takes the work's frame, the working tree it
may edit, and the limits it must respect, and returns a structured result describing what the
invocation amounted to.

The operation SHALL be bounded: it returns, or the run is stopped and it returns anyway. It
SHALL NOT require the caller to poll, resume, or reconnect to a run it started.

#### Scenario: A run returns a structured result rather than output
- **WHEN** a caller invokes an executor with a frame, a working tree and limits
- **THEN** it receives a result carrying an outcome, usage, the transcript location, and whether the tree was left dirty

#### Scenario: A stopped run still returns
- **WHEN** a run is stopped because it exceeded a limit
- **THEN** the call returns a result rather than raising or hanging

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
in one place.

**Reason, carried with the rule:** the turn outcome is frozen because every row ever written is
compared against every other one. The executor vocabulary changes when vendors change. Merging
them would either freeze the soft one or thaw the frozen one.

#### Scenario: Every executor outcome maps to a turn outcome
- **WHEN** an executor produces any outcome in its vocabulary
- **THEN** a turn outcome is derivable from it without a caller-side branch

#### Scenario: The executor never claims there was nothing to do
- **WHEN** an executor produces a result
- **THEN** its outcome is never `nothing-ready`, which is a judgement about the backlog made before any executor is started

### Requirement: Quota exhaustion is never reported as a broken model

Exhausted quota SHALL be carried as its own failure kind, distinguishable in the result from a
task error, a crash, or malformed output.

A result SHALL carry the failure kind on a separate axis from the outcome. Until a turn record
can hold the kind as a typed field, the kind SHALL still reach the record rather than being
dropped at the boundary.

**Reason, carried with the rule:** a factory starved of quota that reads as a broken model gets
the wrong fix applied to it, and the wrong fix is expensive.

#### Scenario: A rate-limited run is distinguishable afterwards
- **WHEN** a run fails because quota was exhausted
- **THEN** the result names the failure kind as rate limiting, separately from its outcome

#### Scenario: The kind survives the narrowing to a record
- **WHEN** an executor result is narrowed to a turn record
- **THEN** the failure kind is still recoverable from that record

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
