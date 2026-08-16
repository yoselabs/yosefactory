## ADDED Requirements

### Requirement: Both reason fields have a stated writer

A component that writes a turn record from an executor result SHALL populate the record's reason
field for the outcome it recorded, whenever the result carries one:

- `outcome: failed` with a typed failure reason in the result → `failure_kind` SHALL carry it
- `outcome: blocked` arising from an executor ending → `blocked_kind` SHALL carry the ending's kind

Neither field SHALL be left null on the grounds that the same information appears in `note`.
Where a writer holds a typed value and the record has a typed field for it, the typed field is
where it goes; `note` carries what only prose can carry.

**A typed field with no writer is not a smaller version of a typed field.** It is a claim in the
schema that nothing in the system supports, and it reads as satisfied to anyone auditing the schema
rather than the rows. Both of this capability's reason fields spent their first change in exactly
that state, deliberately and with the interim stated, and both were then at risk of staying there
indefinitely because nothing failed while they were empty. Auditing the schema is checking the
instrument; auditing the rows is checking the subject.

**On `blocked_kind`'s first change, so a later reader does not misread it:** the field was introduced
correct and with nothing yet to discriminate. Its stated purpose was to separate a resumable block
from a dead end, and at the time no production path produced a `blocked` outcome from an executor
result at all — every such ending was recorded as `failed`. The discriminator was not a dead field
shipped for its own sake; it was the half that had to exist before the collapse underneath it could
be seen. Introducing the vocabulary is what made the live defect describable.

#### Scenario: A recorded failure carries the reason the executor gave

- **WHEN** a turn record is written from an executor result that failed with a typed reason
- **THEN** the record's `failure_kind` is that reason
- **AND** the reason is not represented only inside `note`

#### Scenario: A recorded block carries the kind of block it was

- **WHEN** a turn record is written from an executor ending that means the run is blocked
- **THEN** the record's `blocked_kind` names that ending
- **AND** resumability is derivable from the record without reading free text

#### Scenario: A writer with no typed reason still writes a record

- **WHEN** a supervisor authors a record for a process it killed, having no executor reason
- **THEN** the record is written with a null reason field
- **AND** this remains distinguishable from a writer that had a reason and dropped it, because
  `enforced_by` names the author

### Requirement: An outcome derived from an executor result is not asserted by its writer

Where a turn record's outcome follows from an executor result, the writer SHALL take it from the
declared executor-to-turn mapping. A writer SHALL NOT hard-code an outcome for a class of executor
endings.

This does not constrain outcomes that are *not* derived from an executor result — `nothing-ready` is
a judgement about the backlog made before any executor starts, and a supervisor-authored record for a
process it killed has no result to map. Those writers assert an outcome because there is nothing to
derive one from.

**Reason, carried with the rule:** a record's outcome is the field every other decision is typed
against, and a writer that asserts it can be wrong in a way that no test of the mapping detects. The
mapping and the writer were consistent in the type system and contradictory in behaviour for the
whole period both existed.

#### Scenario: A hard-coded outcome for an executor ending is a defect

- **WHEN** a writing path assigns one turn outcome to every non-success executor ending
- **THEN** that path is incorrect, whatever the mapping declares
- **AND** endings that map to different outcomes are recorded as different outcomes

#### Scenario: A record with no executor result behind it is unaffected

- **WHEN** a record is written for a turn where no executor ran
- **THEN** its outcome is asserted by its writer, with no mapping consulted
