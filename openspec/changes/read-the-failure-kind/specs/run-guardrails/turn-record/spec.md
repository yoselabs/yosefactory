# run-guardrails/turn-record — delta

## ADDED Requirements

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
