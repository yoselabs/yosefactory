## MODIFIED Requirements

### Requirement: A turn is a function of repository state

A turn SHALL read all the state it acts on from its queue (backlog items and questions) and SHALL
leave the state it produces in its queue and, for work carried out during the turn, in its
workspace. Nothing SHALL be passed from one turn to the next by any other means — no held process,
no session, no in-memory carry-over, no environment.

Queue and workspace SHALL be independently named locations (`turn-places`); a turn configured with
one location for both reads and writes exactly as a single-repository turn always has.

A turn SHALL perform, in order: acquire, classify, do exactly one item, record, commit, exit.

#### Scenario: A second turn resumes from the repository alone

- **WHEN** a turn completes and a second turn starts as a fresh process against the same queue
- **THEN** the second turn reads the first turn's committed queue effects and continues from them
- **AND** the second turn requires no argument, file, or variable produced by the first turn other
  than what the first turn committed to the queue

#### Scenario: A turn does exactly one item

- **WHEN** a turn reaches the do step with several items eligible
- **THEN** it acts on exactly one of them
- **AND** the remaining eligible items are untouched and remain eligible for a later turn

### Requirement: Concurrency is safe on one machine and fails loudly across machines

A turn SHALL hold a queue lock for the duration of picking and claiming an item, so two turns
reading one queue cannot both claim the same item. A turn SHALL separately hold a workspace lock,
keyed by the workspace's own identity rather than by which queue dispatched the turn, for the
duration of running the agent and committing its effects — so two turns whose workspace resolves to
the same location cannot both execute there, regardless of which queue dispatched either of them.

When a turn's queue and workspace are the same location, both locks SHALL be satisfied by holding
the tree's single-flight lock once, preserving today's single-repository behaviour exactly.

Cross-machine mutual exclusion requires a compare-and-swap push of the claim, which this capability
does not perform. A turn SHALL refuse to run when it is configured for cross-machine operation
without that push, rather than running unprotected.

#### Scenario: A second turn on the same machine does not start

- **WHEN** a turn is running and another turn is invoked with the same queue and the same workspace
- **THEN** the second turn does not start work, and says the queue and workspace are already in use

#### Scenario: A second turn against the same queue does not claim the same item

- **WHEN** a turn is picking and claiming an item and another turn against the same queue starts
- **THEN** the second turn does not claim the item the first is claiming

#### Scenario: A second turn against the same workspace does not execute concurrently

- **WHEN** a turn is executing its agent and committing against a workspace, and another turn —
  regardless of which queue dispatched it — resolves to the same workspace
- **THEN** the second turn does not start executing against that workspace until the first releases it

#### Scenario: Different queues targeting the same workspace still serialize

- **WHEN** two turns dispatched from two different queues both resolve to the same workspace
- **THEN** they do not execute against that workspace concurrently

#### Scenario: Cross-machine operation without compare-and-swap is refused

- **WHEN** a turn is configured to coordinate with other machines but the compare-and-swap push is
  not enabled
- **THEN** the turn refuses to run and names the missing protection
