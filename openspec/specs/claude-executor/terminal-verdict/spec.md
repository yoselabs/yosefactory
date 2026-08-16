# claude-executor/terminal-verdict Specification

## Purpose
Fixes what is allowed to decide how a run ended: the agent's own terminal event, and nothing
else. The process exit code is recorded as evidence and never consulted for the verdict.
## Requirements
### Requirement: The terminal event is the only verdict

An executor SHALL derive a run's outcome from the terminal event the agent emits at the end of
the run, and from no other source.

#### Scenario: The verdict comes from the stream
- **WHEN** a run emits a terminal event
- **THEN** the outcome is derived from that event's own fields

#### Scenario: Intermediate output is not a verdict
- **WHEN** a run emits errors or refusals as ordinary output without a terminal event
- **THEN** those are not read as the run's outcome

### Requirement: Absence of a terminal event is failure, on any exit code

A run that produces no terminal event SHALL be recorded as failed, including when the process
exits zero.

**Reason, carried with the rule:** in-run failures — a missing or expired credential among
them — are printed as ordinary output and the process still exits zero. Treating a zero exit as
success turns the most common silent failure into a recorded success.

#### Scenario: Exit zero with no terminal event is failed
- **WHEN** a run exits with status zero and emitted no terminal event
- **THEN** the outcome is failed

#### Scenario: The reason names what was missing
- **WHEN** a run fails for want of a terminal event
- **THEN** the result says so, rather than reporting an unexplained failure

### Requirement: The exit code is evidence, never the verdict

The process exit code SHALL be recorded on the result and SHALL NOT determine the outcome.

The exit code MAY be used only to name *which kind of missing verdict* occurred — a run
terminated by a stop signal with no terminal event is a cancellation rather than a
malformed-output failure.

#### Scenario: A non-zero exit with a successful terminal event is success
- **WHEN** a run emits a terminal event reporting success but exits non-zero
- **THEN** the outcome is success and the exit code is recorded alongside it

#### Scenario: A stop signal with no verdict reads as cancelled
- **WHEN** a run is terminated by a stop signal before emitting a terminal event
- **THEN** the outcome is cancelled rather than failed-for-malformed-output

### Requirement: Failure kinds are read from structured fields, never from error text

Authentication failure and quota exhaustion SHALL be recognised from structured fields the
agent emits — a status code, or a dedicated event type — and SHALL NOT be recognised by
matching the text of an error message.

**Reason, carried with the rule:** message text is not a contract. A wording change silently
reclassifies every run that hits that path, and the reclassification is invisible.

#### Scenario: Quota exhaustion is observed, not inferred
- **WHEN** a run hits a quota limit
- **THEN** it is classified from the dedicated event or status field rather than from message text

#### Scenario: An unrecognised error is a task error, not a guess
- **WHEN** a run reports an error carrying no recognised status or event type
- **THEN** it is classified as a task error rather than assigned a specific kind by text matching

