## ADDED Requirements

### Requirement: A turn's spend row is committed in the same commit as its run record

When a turn ran an executor, the turn SHALL write the resulting cost as a spend row and SHALL
include that row's path in the same `commit()` call that stages the turn's own run record. The turn
SHALL NOT write the spend row anywhere the commit that follows cannot reach, and SHALL NOT commit
the run record without attempting to commit the spend row alongside it in the same git operation.

Zero cost is a real value and SHALL still produce a row: absence SHALL NOT be read as "this run
never happened."

**Reason, carried with the rule:** a spend row written to disk but never named in a commit's
pathspec is invisible to `git commit -- <paths>` by construction (Article V) — it survives on disk
until something else happens to sweep it up, and nothing does. A row written to a different
repository than the one the turn commits into is invisible for a stronger reason: no pathspec in any
commit against that repository can ever name it. Both were true before this requirement; a green
`make check`, a pushed run record, and CI's own logs all read as success while the row was silently
lost.

#### Scenario: A turn that spent money commits its spend row alongside its run record

- **WHEN** a turn runs an executor that reports a nonzero cost, and the turn's outcome is recorded
- **THEN** the same commit that carries the turn's run record also carries a spend row naming that
  run's id and cost
- **AND** the spend row is present in `git show HEAD` for that commit, not merely written to disk

#### Scenario: A turn that spent exactly zero still commits a row

- **WHEN** a turn runs an executor that reports zero cost
- **THEN** a spend row for that run's id, carrying zero, is committed alongside the run record
- **AND** a reader of the spend log cannot distinguish "this run cost nothing" from "this run's cost
  was never recorded" by the row's absence, because there is no absence

#### Scenario: A turn that never ran an executor commits no spend row

- **WHEN** a turn ends without ever invoking an executor (nothing eligible and nothing to plan)
- **THEN** no spend row is written or committed for that turn

#### Scenario: A spend-write failure does not cost the turn its run record or the agent's delivered commit

- **WHEN** the spend row fails to write (e.g. the underlying file write raises)
- **THEN** the turn's run record is still written and committed
- **AND** any workspace commit the turn already delivered for a `done` proposal is unaffected
- **AND** the turn's note names the spend-recording failure

#### Scenario: The spend row is written to the repository the turn's commit actually stages

- **WHEN** a turn's queue and the package's own installed location are different directories
- **THEN** the spend row is written inside the queue repository, not resolved from the package's own
  location
- **AND** the commit that stages the run record is able to name and stage the spend row's path,
  because both live in the same repository
