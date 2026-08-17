# board-projection Specification

## ADDED Requirements

### Requirement: A command's effect is committed to git, not left in the working tree

Every event `ingest()` applies or rejects SHALL be committed to the target repository — the item
or question log it wrote to, and the consumed-log entry recording the outcome — using the same
commit path (`runtime.turn.commit()`, explicit pathspecs, platform trailers) every other writer in
this repository uses. `ingest()` SHALL NOT leave an applied command as an uncommitted working-tree
change.

**Reason, carried with the rule:** an uncommitted write does not move the queue's `HEAD`, so a
caller relying on `HEAD` movement to detect that something happened (`turn-loop/board-wiring`'s
`EXTERNAL_EVENT` wake) would never see it. A working-tree-only change is also invisible to `git
log`, to a push, and to any reader treating git as the source of truth — architecture.md §7's own
premise for why the board is safe to project publicly.

#### Scenario: An applied command is a real commit
- **WHEN** `ingest()` successfully applies a command
- **THEN** the target log's new event and the consumed-log's new entry are both present in a
  single commit
- **AND** the repository's working tree is clean with respect to those paths afterward

#### Scenario: A rejected command still commits the consumed-log entry
- **WHEN** `ingest()` rejects a command
- **THEN** the consumed-log's rejection entry is committed
- **AND** no partial, uncommitted state is left for either the target log or the consumed log
