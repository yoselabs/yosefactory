## MODIFIED Requirements

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
