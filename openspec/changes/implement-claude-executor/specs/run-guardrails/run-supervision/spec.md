## ADDED Requirements

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

## MODIFIED Requirements

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

#### Scenario: A killed run is not a silent run
- **WHEN** the supervisor terminates a run for any reason
- **THEN** a record exists for that run carrying `enforced_by: harness`

#### Scenario: A torn tree is recorded as torn
- **WHEN** a run is terminated mid-edit leaving uncommitted modifications
- **THEN** the supervisor's record carries `dirty: true`

#### Scenario: A verdict flushed during the grace period does not reclaim authorship
- **WHEN** a terminated run emits a terminal verdict inside its grace period
- **THEN** the record still carries `outcome: failed` and `enforced_by: harness`, and the flushed verdict is discarded
