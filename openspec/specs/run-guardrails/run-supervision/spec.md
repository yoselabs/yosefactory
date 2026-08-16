# run-guardrails/run-supervision Specification

## Purpose
Bounds a run in wall-clock time and in turns, prevents two runs overlapping on the same
working tree, and guarantees that a run stopped by the harness still leaves a truthful
record behind.
## Requirements
### Requirement: Every run is bounded by a wall clock

The supervisor SHALL terminate any run exceeding a configured wall-clock deadline. The
deadline SHALL default to a value well below the six-hour ceiling that hosted CI applies,
so that the supervisor's stop is always the one that fires first.

**Reason, carried with the rule:** nine executor surfaces were assessed and none of them
enforces a wall clock. If the harness does not, nothing does.

#### Scenario: An overrunning run is terminated
- **WHEN** a run exceeds its wall-clock deadline
- **THEN** the supervisor terminates it

#### Scenario: The harness stop precedes the CI stop
- **WHEN** the configured deadline is compared against the hosting platform's own timeout
- **THEN** the configured deadline is the smaller of the two

### Requirement: Every run is bounded by a turn ceiling

The supervisor SHALL terminate any run exceeding a configured maximum number of turns.
There is no default ceiling in the underlying executors, so the ceiling SHALL always be
set rather than left unspecified.

This ceiling is a loop-runaway guard. It is **not** a spend cap, and SHALL NOT be
described or configured as one.

#### Scenario: An unbounded loop is stopped
- **WHEN** a run exceeds its configured turn ceiling
- **THEN** the supervisor terminates it

#### Scenario: A run with no configured ceiling does not start
- **WHEN** a run is requested with no turn ceiling configured
- **THEN** the supervisor refuses to start it

### Requirement: A harness stop produces a supervisor-authored record

When the supervisor terminates a run, it SHALL append a turn record itself, carrying
`outcome: failed`, `enforced_by: harness`, and a `dirty` value determined by inspecting the
working tree after termination.

**Reason, carried with the rule:** termination is a kill, and a killed process writes
nothing. Without the supervisor writing on its behalf, the most dangerous runs are exactly
the ones that leave no trace.

#### Scenario: A killed run is not a silent run
- **WHEN** the supervisor terminates a run for any reason
- **THEN** a record exists for that run carrying `enforced_by: harness`

#### Scenario: A torn tree is recorded as torn
- **WHEN** a run is terminated mid-edit leaving uncommitted modifications
- **THEN** the supervisor's record carries `dirty: true`

### Requirement: Runs do not overlap on the same working tree

The supervisor SHALL prevent a second run starting while another holds the same working
tree, using an exclusive lock or an equivalent single-flight mechanism.

A run that cannot acquire the lock SHALL exit without doing work, and SHALL NOT wait
indefinitely for the holder.

**Reason, carried with the rule:** all workers share one tree. Two concurrent runs editing
it produce a state neither of them authored.

#### Scenario: A second run declines to start
- **WHEN** a run is invoked while another holds the lock
- **THEN** the second run exits without performing work

#### Scenario: The lock is released on termination
- **WHEN** a run is terminated by the supervisor
- **THEN** the lock is released so a later run can start

### Requirement: The supervisor is invoked, not resident

The supervisor SHALL be a function a job calls for the duration of one run, and SHALL NOT
require a persistent process, daemon, queue, or scheduler of its own to be running between
runs.

#### Scenario: Nothing runs between runs
- **WHEN** no run is in progress
- **THEN** no supervisor process is required to exist

