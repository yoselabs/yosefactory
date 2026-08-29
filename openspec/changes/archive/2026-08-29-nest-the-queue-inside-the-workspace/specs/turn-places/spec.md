## MODIFIED Requirements

### Requirement: A turn's four roles are independently addressable

A turn SHALL read its queue (backlog items and questions) and its ledger (turn records) from
locations that are named separately from the location it executes work in. Each of the four roles —
queue, ledger, lock, workspace — SHALL be resolvable to a location of its own.

A queue MAY be a subdirectory of the workspace's own repository rather than a repository of its own.
In that configuration, the queue and the workspace SHALL share one lock: both `queue_lock` and
`workspace_lock` SHALL resolve to the workspace repository's own lock file, never to a lock path
computed under the queue subdirectory, which is not itself a repository.

#### Scenario: A turn targeting one repository behaves as before

- **WHEN** a turn is configured with one location for all four roles
- **THEN** the turn's queue, ledger, lock, and workspace all resolve to that one location
- **AND** its observable behaviour is unchanged from a turn that named a single repository directly

#### Scenario: A turn's workspace differs from its queue

- **WHEN** a turn is configured with a queue location and a separate workspace location
- **THEN** the turn reads backlog items and questions from the queue location only
- **AND** the agent's working directory, test command, tree-cleanliness check, and commits all act on
  the workspace location only

#### Scenario: A turn's queue is nested inside its workspace

- **WHEN** a turn is configured with a queue location that is a subdirectory of its workspace
  location, both backed by the same underlying repository
- **THEN** the queue's backlog items, questions, and ledger are read from and written to that
  subdirectory
- **AND** commits made against the queue land in the same repository history as commits made against
  the workspace
- **AND** the queue lock and the workspace lock resolve to the same file, so a queue-side operation
  and a workspace-side operation on the same turn never race against two different locks guarding
  one tree

#### Scenario: Two different workspaces never share a queue

- **WHEN** two turns are each configured with their queue nested inside a different workspace
- **THEN** an item present in one workspace's queue is never visible to, pickable by, or claimable
  from the other workspace's queue
