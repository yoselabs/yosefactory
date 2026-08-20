# claude-executor/model-and-effort Specification

## Purpose
TBD - created by archiving change pin-the-executor-and-close-the-push-grant. Update Purpose after archive.
## Requirements
### Requirement: Every invocation names its model and effort explicitly

The executor SHALL send an explicit model and an explicit effort level on every invocation. Neither
SHALL be left absent for the binary to default, and neither SHALL be represented as an optional
value that can be unset — a caller that states no opinion still gets a real, named value.

**Reason, carried with the rule:** every agent this factory has run used whatever the binary
defaulted to at the moment it ran, and nothing recorded which. Costs across runs are not comparable
when the thing that determines cost was never held fixed.

#### Scenario: A caller supplying no opinion still sends a named model and effort
- **WHEN** an invocation is built with no model or effort stated by the caller
- **THEN** the invocation names a specific model and a specific effort level
- **AND** neither is represented internally as absent or unset

#### Scenario: A caller may override either value
- **WHEN** a caller supplies a different model or effort
- **THEN** the invocation sends exactly what the caller supplied

### Requirement: The pinned default is `claude-sonnet-5` at effort `medium`

Absent an explicit override, the executor SHALL invoke `claude-sonnet-5` at effort `medium`.

#### Scenario: The default invocation
- **WHEN** an invocation is built with no override
- **THEN** it names `claude-sonnet-5` as the model and `medium` as the effort

### Requirement: A turn's record carries the model and effort that produced it

The turn record SHALL carry the model and the effort level used for the run it describes. The model
SHALL be taken from the run's own startup report when that report is available, in preference to
the value the invocation requested. The effort SHALL be taken from the value the invocation
requested, and this SHALL be stated as a weaker receipt than the model field, because the run's own
startup report does not carry it.

**Reason, carried with the rule:** a flag sent is an intent; the agent's own startup report of what
it loaded is evidence, and only the second can disagree with the first. This capability already
trusts that report for the isolation contract (`claude-executor/isolation-invocation`) — the same
instrument applies here for the one field the report actually carries.

#### Scenario: The model is read back from the run's startup report
- **WHEN** a run's startup report names the model it is running
- **THEN** the turn record's model field carries that reported value

#### Scenario: The model falls back to the requested value only when no startup report exists
- **WHEN** a run produces no startup report at all
- **THEN** the turn record's model field carries the value the invocation requested

#### Scenario: The effort is recorded from what was requested, not verified
- **WHEN** a run completes
- **THEN** the turn record's effort field carries the effort level the invocation requested
- **AND** nothing in this capability claims that value was independently verified

### Requirement: A pre-existing record with no model or effort field remains readable

A turn record written before this capability existed SHALL still be readable. Its model and effort
SHALL read as not-recorded, distinguishable from a record that carries an empty or blank value by
convention rather than by any value this capability would ever write for a real run.

**Reason, carried with the rule:** [[D002]] — nothing is ever deleted, and a schema addition must
not retroactively invalidate what a prior run legitimately wrote before the field existed.

#### Scenario: An old record without the fields still loads
- **WHEN** a turn record written before this capability existed is read
- **THEN** it loads without error
- **AND** its model and effort read as not-recorded

