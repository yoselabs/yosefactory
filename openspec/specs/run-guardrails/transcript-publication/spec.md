# run-guardrails/transcript-publication Specification

## Purpose
This repository is public. `TurnRecord` already refuses a home-rooted absolute path at write time
(`run-guardrails/turn-record`'s "Records carry no secrets and no host identity"), but the raw agent
transcript is a separate file, written directly by the executor, that never passes through that
check. This capability states what stops the transcript — and any other staged file — from
publishing a host path anyway.
## Requirements
### Requirement: The raw transcript stream is never committed

`ledger/runs/*.stream.jsonl` SHALL be excluded from version control. The file MAY still be written
to that path by the executor and SHALL remain readable on local disk; only its presence in the git
index and in any commit is forbidden.

**Reason, carried with the rule:** the raw stream is the executor's unfiltered stdout and carries
whatever the agent read or wrote that turn, including absolute host paths `TurnRecord`'s own guard
was never positioned to see. It stays valuable as local evidence — this program's own discipline is
to check the subject, not the instrument — so it is kept, not deleted; only its publication is
refused.

#### Scenario: A transcript path is refused even if forced onto the index
- **WHEN** a caller attempts to stage a file matching `ledger/runs/*.stream.jsonl`, including via
  a forced add that bypasses `.gitignore`
- **THEN** a commit containing that path is refused

#### Scenario: The transcript is still written and still readable
- **WHEN** a turn runs to completion
- **THEN** its transcript exists on disk at `ledger/runs/<run_id>.stream.jsonl`
- **AND** it is not present in `git status` as a trackable addition once `.gitignore` covers it

### Requirement: A staged file carrying an absolute host path is refused

A commit SHALL be refused if any staged file's content contains a literal path rooted at
`/Users/`, `/home/`, or `/root` — the same pattern `run-guardrails/turn-record` already applies to
`TurnRecord` fields, applied here to every staged file rather than to one record's fields alone.
The check SHALL be applied per line; a line carrying the literal marker `hostpath-allow` SHALL be
exempt from this requirement, and no other line in the same file is exempted by that marker.

This check is independent of the transcript-path check above: it exists for every other file this
repository might ever commit, not only for `ledger/runs/`.

**Reason, carried with the rule:** the transcript check above is scoped to one known filename
pattern. A host path can reach a commit through any file — a debug print left in a diff, a pasted
error message, a fixture copied from a real run. The pattern-based check is the general form of the
same refusal, and it is what a future change that isn't `ledger/runs/*` is caught by.

#### Scenario: A staged host path is refused
- **WHEN** a file staged for commit contains a substring matching `/Users/`, `/home/`, or `/root`
  as a path (not merely as a bare word)
- **THEN** the commit is refused, naming the offending file

#### Scenario: A relative or example path is not flagged
- **WHEN** a staged file contains a path that is not rooted at `/Users/`, `/home/`, or `/root` —
  including a bare word like `Users` with no leading slash
- **THEN** the commit is not refused on that basis

#### Scenario: A marked example line is not flagged, but the rest of the file still is
- **WHEN** a staged file contains one line matching the pattern and carrying `hostpath-allow`, and
  a second, unmarked line also matching the pattern
- **THEN** the commit is refused, naming the file, because of the second line
- **AND** the marked line alone would not have caused a refusal

#### Scenario: The check runs both before and after the commit lands
- **WHEN** a commit is about to be created
- **THEN** a staged-content check runs and can refuse it before it exists
- **AND** a separate check of the commit that actually landed at `HEAD` remains available to run
  afterward, so a commit made with hooks skipped is still caught the next time that check runs

