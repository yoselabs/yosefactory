## ADDED Requirements

### Requirement: The workspace's platform-produced commit is the gate-certified boundary commit, amended in place

When a turn reaches `may_write_done` and the gate passes, the platform SHALL apply its trailers
(`Co-Authored-By: yosefactory <yosefactory@yoselabs.dev>` and `Yosefactory-Run: <run_id>`) to the
commit at the workspace's `HEAD` by amending it, using the same trailer-composition path the queue's
commits use. The platform SHALL NOT create a new commit for this purpose and SHALL NOT amend or
rewrite any commit other than the one at `HEAD` at the moment the gate passed.

**Reason, carried with the rule:** `tree_clean` already requires the workspace be free of
uncommitted changes before `may_write_done` can pass, so by the time delivery could run there is
nothing left to commit — only the commit already there to mark. `HEAD` at that instant is the one
commit the gate has actual, checked evidence about; every earlier commit the agent made during the
same turn is a checkpoint, untouched, exactly as `orchestration.md`'s ruling requires.

#### Scenario: The boundary commit carries both trailers after delivery

- **WHEN** a turn's agent proposes `done`, the gate passes, and the workspace's `HEAD` at that moment
  is a commit the agent made during the turn
- **THEN** that commit, after delivery, carries `Co-Authored-By: yosefactory <yosefactory@yoselabs.dev>`
  and `Yosefactory-Run: <run_id>`
- **AND** its SHA changes (the amend produces a new commit object), but the subject, body, and any
  trailer it already carried are unchanged

#### Scenario: Earlier checkpoints in the same turn are untouched

- **WHEN** the agent made more than one commit in the workspace during a single turn before proposing
  `done`
- **THEN** only the commit at `HEAD` when the gate passed is amended
- **AND** every earlier commit from the same turn keeps its original SHA, message, and trailers

### Requirement: A workspace commit is never invented

When a turn reaches the point delivery would run, and the workspace's `HEAD` has not moved since
before the executor ran, the platform SHALL NOT create or amend any commit. The turn's record SHALL
show no workspace commit for that run.

**Reason, carried with the rule:** a turn can pass the gate having made no workspace change — an
investigation that concludes `done` with nothing to commit. Manufacturing a commit to carry the
trailers would assert a workspace effect that did not happen, which is exactly the kind of
self-report this design's verification gate exists to refuse.

#### Scenario: No commit is created when nothing changed

- **WHEN** a turn's agent proposes `done` and the gate passes, and the workspace's `HEAD` is the same
  commit it was before the executor ran
- **THEN** no commit is created or amended in the workspace
- **AND** the turn's record carries no workspace commit for that run

### Requirement: A reader holding only a run finds its workspace commit

The turn record SHALL carry the delivered workspace commit's SHA, so that a reader holding the run
alone can reach the commit without searching the workspace's history, completing the other half of
the join `Yosefactory-Run` already provides in reverse.

#### Scenario: The record names the commit it produced

- **WHEN** a turn delivers a workspace commit
- **THEN** the turn's record carries that commit's SHA
- **AND** the commit itself, read independently, carries a `Yosefactory-Run` trailer equal to that
  run's id

#### Scenario: The join resolves in both directions

- **WHEN** a reader holds only the workspace commit
- **THEN** its `Yosefactory-Run` trailer names a run whose record exists in the ledger
- **AND** when a reader holds only that run's record
- **THEN** its recorded workspace commit SHA is present in the workspace's git history

### Requirement: The amend does not re-ask the workspace's own hooks a second question

Amending the boundary commit SHALL NOT re-run the workspace's own commit hooks. The diff the amended
commit represents already passed those hooks when the agent's own commit produced it; the amend
changes only the message.

**Reason, carried with the rule:** re-running hooks on an unchanged tree asks the same question the
workspace's gate already answered, at the platform's expense, and introduces a new and unrelated
failure surface — a hook validating message syntax against a convention that does not expect this
platform's trailer names could reject a commit whose diff is fine, for a reason unconnected to the
work the gate already verified.

#### Scenario: A workspace with hooks still receives its delivered commit

- **WHEN** the workspace has its own pre-commit or commit-msg hooks configured
- **THEN** delivery still amends the boundary commit with both trailers
- **AND** the workspace's hooks are not invoked a second time by the amend
