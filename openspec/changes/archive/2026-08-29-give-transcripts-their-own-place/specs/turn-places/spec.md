## MODIFIED Requirements

### Requirement: A turn's four roles are independently addressable

A turn SHALL read its queue (backlog items and questions) and its ledger (turn records) from
locations that are named separately from the location it executes work in, and SHALL write the
executor's raw transcript to a location that is named separately from the ledger. Each of these five
roles — queue, ledger, transcripts, lock, workspace — SHALL be resolvable to a location of its own.

A queue MAY be a subdirectory of the workspace's own repository rather than a repository of its own.
In that configuration, the queue and the workspace SHALL share one lock: both `queue_lock` and
`workspace_lock` SHALL resolve to the workspace repository's own lock file, never to a lock path
computed under the queue subdirectory, which is not itself a repository.

Transcripts SHALL default to the ledger's own location when a caller does not name one explicitly, so
that a turn configured with no opinion about transcripts behaves exactly as a turn that named a
single ledger location for both roles.

#### Scenario: A turn targeting one repository behaves as before

- **WHEN** a turn is configured with one location for all four original roles
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

#### Scenario: Transcripts default to the ledger when unconfigured

- **WHEN** a turn is configured with no explicit transcripts location
- **THEN** the executor's raw transcript is written to the same location as the ledger's own turn
  records
- **AND** this matches the location every turn wrote its transcript to before the transcripts role
  existed as a separate concept

#### Scenario: Transcripts are configured to a location outside the workspace

- **WHEN** a turn's queue is nested inside its workspace, and the turn is configured with a
  transcripts location that is not inside the workspace
- **THEN** the executor's raw transcript is written to that configured location
- **AND** the workspace's own working tree contains no untracked file for that transcript
- **AND** the turn's ledger records (`.start` files and terminal turn records) are unaffected and
  continue to be written to, and committed from, the ledger's own location inside the workspace

### Requirement: The workspace's own configuration is not the queue's concern

Nothing about which repository a turn's queue lives in SHALL constrain, or be constrained by, which
repository the turn's workspace lives in. A queue serving turns against several different workspaces,
and a workspace receiving turns from several different queues, are both legal configurations.

#### Scenario: One queue dispatches turns against different workspaces

- **WHEN** two turns from the same queue are each configured with a different workspace location
- **THEN** neither turn's queue-side state (backlog, questions, ledger) is affected by which
  workspace the other targets

### Requirement: A cross-repository turn's record is a duplicate risk, never a false claim

When a turn's workspace differs from its queue, a turn that is interrupted after the workspace holds
new work but before the queue records the outcome SHALL leave the queue in a non-terminal, resumable
state. The queue SHALL NOT record an outcome for work that did not verifiably complete, and SHALL NOT
be left permanently unable to reconcile with what the workspace actually holds.

**Reason, carried with the rule:** this is not a new hazard introduced by separating queue from
workspace — the same window exists between an agent's own commit and the queue's terminal record when
both live in one repository. Splitting the repository makes the two sides visibly distinct; it does
not create disagreement that was not already possible. What differs is that the workspace effect and
the queue's record of it are now two independent git histories with no shared commit to point at,
so detecting a disagreement — not preventing one, which no design here achieves — requires each side
to name the other.

#### Scenario: A turn interrupted after a workspace commit but before its queue record

- **WHEN** the workspace holds a commit made by the turn's agent, and the turn is interrupted before
  the queue's outcome for that work is committed
- **THEN** the queue shows the item in a non-terminal, resumable state
- **AND** nothing in the queue asserts that the work did not happen or that it succeeded

#### Scenario: A resumed item may re-attempt work already landed in the workspace

- **WHEN** an item left non-terminal by an interrupted cross-repository turn is later reclaimed
- **THEN** the reclaiming turn is not prevented from attempting the goal again
- **AND** this capability does not guarantee the reattempt notices the earlier workspace commit
