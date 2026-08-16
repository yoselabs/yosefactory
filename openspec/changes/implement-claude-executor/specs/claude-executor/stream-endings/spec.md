## Purpose

Separates the end of a turn from the end of a run in the agent's event stream, so that a run is
bounded by a turn count that is readable while it is still going rather than one that arrives
only after it is over.

## ADDED Requirements

### Requirement: A turn ending and a run ending are distinct events

An executor SHALL distinguish the event that closes one turn from the event that closes the
run, and SHALL NOT treat the first as the second.

**Reason, carried with the rule:** an agent that retries emits a turn ending mid-run. Keying the
verdict on it truncates the run and reports whatever the first turn happened to say.

#### Scenario: A turn ending does not end the run
- **WHEN** a run emits a turn-ending event and continues working
- **THEN** the executor does not treat the run as finished

#### Scenario: The run ending is the one that supplies the verdict
- **WHEN** a run emits both turn endings and a run ending
- **THEN** the outcome is derived from the run ending only

### Requirement: The turn count is live, not terminal

The turn count used to enforce a turn ceiling SHALL be readable while the run is in progress.

**Reason, carried with the rule:** the terminal event carries a turn total, and it arrives after
the run is over — which is too late to bound anything. A ceiling that can only be evaluated
after the fact is a report, not a guard.

#### Scenario: The ceiling can fire mid-run
- **WHEN** a run exceeds its turn ceiling while still executing
- **THEN** the count is available to the supervisor at that moment and the run is stopped

#### Scenario: The count does not depend on the run finishing
- **WHEN** a run is stopped before it emits a run ending
- **THEN** the turns it completed are still known

### Requirement: A partial trailing record is not a malformed stream

A reader over a run's event stream SHALL consume only whole records, and SHALL treat an
incomplete trailing record as not yet written rather than as corruption.

The reader SHALL be safe to invoke before the run has produced any output at all.

#### Scenario: A half-written record is left for the next read
- **WHEN** the stream is read while a record is only partly flushed
- **THEN** that record is not consumed and no error is raised

#### Scenario: Reading before the run starts is not an error
- **WHEN** the stream is read before the agent has written anything
- **THEN** the read reports no events rather than failing
