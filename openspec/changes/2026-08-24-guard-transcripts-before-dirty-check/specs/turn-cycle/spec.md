## MODIFIED Requirements

### Requirement: A turn's own raw transcript never counts as the workspace's uncommitted work

When a turn's ledger is nested inside its workspace, the turn SHALL guarantee — before any agent
runs and before any transcript can be written — that the raw transcript files the executor writes
are excluded from the workspace's tracked state, so that a transcript's mere presence on disk never
causes the verification gate's tree-cleanliness check to fail.

This guarantee SHALL hold regardless of which repository the workspace is (this platform's own
source tree, or a foreign repository the turn is pointed at), and SHALL NOT depend on that
repository's own committed configuration already carrying the exclusion.

When a turn runs inside the self-chaining loop, the guarantee SHALL be asserted before the loop's
own pre-flight dirty-tree check, so a workspace already carrying untracked transcripts from a prior
turn is excluded before that check inspects it, not only after the loop's first turn runs.

#### Scenario: A transcript is written during a turn whose ledger nests inside its workspace

- **WHEN** a turn runs with its ledger located inside its workspace (the single-repository
  configuration)
- **AND** the executor writes a raw transcript file into the ledger during the turn
- **THEN** the workspace's tree-cleanliness check does not count that transcript file as an
  uncommitted change

#### Scenario: The ledger's other files are unaffected

- **WHEN** the same turn commits its own bookkeeping files into the ledger (the run's declared
  marker and its terminal record)
- **THEN** those files remain trackable and committable exactly as before — the exclusion applies
  only to raw transcript files, never to the ledger directory as a whole

#### Scenario: The ledger lives outside the workspace entirely

- **WHEN** a turn's ledger is located in a different repository from its workspace
- **THEN** no exclusion is written into the workspace, because nothing there could cause a
  transcript to be mistaken for the workspace's own uncommitted work

#### Scenario: A `Places.local` workspace already carries untracked transcripts before the loop starts

- **WHEN** the self-chaining loop is started against a `Places.local` workspace that already has
  untracked raw transcript files on disk (a workspace that took a turn before this exclusion
  existed)
- **THEN** the exclusion is asserted before the loop's dirty-tree refusal check runs
- **AND** the loop starts successfully instead of refusing to start
