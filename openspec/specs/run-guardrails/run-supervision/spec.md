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

When the supervisor terminates a run, a turn record SHALL exist for that run carrying
`outcome: failed`, `enforced_by: harness`, and a `dirty` value determined by inspecting the
working tree after termination.

**A harness stop decides the authorship and the outcome, and outranks any verdict the agent
flushed on the way down.** An agent given a grace period before termination does emit a
terminal verdict inside it — measured, not assumed — and that verdict describes a run that was
cut short. Honouring it would let a wall-clock kill be recorded as the agent's own outcome, up
to and including success, which is the one thing `enforced_by` exists to prevent.

**Reason, carried with the rule:** termination is a kill, and a killed process writes nothing.
Without the supervisor authoring on its behalf, the most dangerous runs are exactly the ones
that leave no trace.

**One clause of the previous version was neutralised rather than re-promoted, and it belongs to
another change.** The previous text required the supervisor to *append* the record itself. The
supervisor now authors the record and returns it, persisting it only when handed a writer, so
re-promoting the original sentence would have written a mechanism claim into this spec that had
already stopped being true. It is stated here as an existence claim instead; every normative
element — `failed`, `enforced_by: harness`, and `dirty` determined by inspection — is unchanged.
Which component persists the record is specified by the capability that owns the writer split,
not here.

#### Scenario: A killed run is not a silent run
- **WHEN** the supervisor terminates a run for any reason
- **THEN** a record exists for that run carrying `enforced_by: harness`

#### Scenario: A torn tree is recorded as torn
- **WHEN** a run is terminated mid-edit leaving uncommitted modifications
- **THEN** the supervisor's record carries `dirty: true`

#### Scenario: A verdict flushed during the grace period does not reclaim authorship
- **WHEN** a terminated run emits a terminal verdict inside its grace period
- **THEN** the record still carries `outcome: failed` and `enforced_by: harness`, and the flushed verdict is discarded

### Requirement: Runs do not overlap on the same working tree

The supervisor SHALL prevent a second run starting while another holds the same workspace, using an
exclusive lock or an equivalent single-flight mechanism keyed by the workspace's own identity. Two
runs whose workspace resolves to the same location SHALL NOT overlap, regardless of which caller or
which queue dispatched either run.

A run that cannot acquire the lock SHALL exit without doing work, and SHALL NOT wait indefinitely
for the holder.

**Reason, carried with the rule:** all workers share one tree, and two concurrent runs editing it
produce a state neither of them authored. Keying the lock by workspace identity rather than by
caller is what makes this hold even when a workspace receives runs dispatched from more than one
queue — a lock scoped to the dispatching queue alone cannot see that collision.

#### Scenario: A second run declines to start

- **WHEN** a run is invoked against a workspace while another run holds the lock for that same
  workspace
- **THEN** the second run exits without performing work

#### Scenario: Two callers targeting the same workspace still serialize

- **WHEN** two runs are invoked by different callers, and both resolve to the same workspace
- **THEN** they do not overlap execution against that workspace

#### Scenario: The lock is released on termination

- **WHEN** a run is terminated by the supervisor
- **THEN** the lock is released so a later run against that workspace can start

### Requirement: The supervisor is invoked, not resident

The supervisor SHALL be a function a job calls for the duration of one run, and SHALL NOT
require a persistent process, daemon, queue, or scheduler of its own to be running between
runs.

#### Scenario: Nothing runs between runs
- **WHEN** no run is in progress
- **THEN** no supervisor process is required to exist

### Requirement: The run's own event stream is reachable by the caller

The supervisor SHALL allow its caller to name a destination for the supervised run's output, so
that the caller can read the run's own events while the run is in progress and after it ends.

The default SHALL preserve the behaviour of a caller that names no destination.

**Reason, carried with the rule:** the verdict lives in the run's terminal event, and a run
whose output the supervisor cannot hand back has no reachable verdict. This is the difference
between a supervisor that bounds a run and one that can also report what the run decided.

#### Scenario: A named destination captures the run's events
- **WHEN** a caller supervises a run and names a destination for its output
- **THEN** the run's events are written there and are readable by the caller

#### Scenario: A caller that names nothing is unaffected
- **WHEN** a caller supervises a run without naming a destination
- **THEN** the run behaves as it did before this capability existed

