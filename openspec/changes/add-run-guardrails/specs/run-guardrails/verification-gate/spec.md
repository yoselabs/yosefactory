## Purpose

Makes a claim of completed work unwritable until something other than the claimant has
confirmed the claimed effect exists, so that a run reporting success and a run succeeding
are the same event.

## ADDED Requirements

### Requirement: A `done` transition requires an independent check

A transition marking work as `done` SHALL be written only after an independent check
confirms the claimed effect exists. The check SHALL be performed by the verification gate,
not by the agent that performed the work, and SHALL derive its verdict from inspecting the
repository and its tooling rather than from anything the agent reported.

An agent's self-report is not evidence and SHALL NOT satisfy this requirement, whatever
form it takes — a message, a structured field, a zero exit code.

**Reason, carried with the rule:** in this program, defects surfaced by checks internal to
the actor = 0; by foreign evidence = 5. The recorded instance is an agent announcing a
pull request when only the branch existed.

#### Scenario: A run that claims work it did not do fails
- **WHEN** a run reports success but the claimed effect is absent from the repository
- **THEN** the gate fails the run
- **AND** no `done` transition is written

#### Scenario: A self-report cannot substitute for the check
- **WHEN** an agent reports success and the gate has not run
- **THEN** no `done` transition is written

#### Scenario: A confirmed effect passes
- **WHEN** the claimed effect is present and every check passes
- **THEN** the `done` transition is written

### Requirement: The check covers tests, commits, and tree state

The gate SHALL confirm, at minimum, that the test suite passes, that the claimed commit is
present in the repository history, and that the working tree holds no uncommitted
modifications.

Each of these SHALL be evaluated independently, and the gate SHALL fail if any one of them
fails.

#### Scenario: A claimed commit that is not in the log fails
- **WHEN** a run claims a commit and that commit is absent from the history
- **THEN** the gate fails and names the missing commit

#### Scenario: A dirty tree fails
- **WHEN** the working tree holds uncommitted modifications at verification time
- **THEN** the gate fails and reports the tree as dirty

#### Scenario: A failing test suite fails
- **WHEN** the test suite does not pass
- **THEN** the gate fails and reports the test failure

### Requirement: A zero exit code is never the verdict

The gate SHALL NOT accept a process exit code as evidence of success. Where a run produces
no terminal structured verdict, the gate SHALL treat the run as failed even if the process
exited zero.

**Reason, carried with the rule:** executors are documented to print in-run failures,
including missing authentication, as ordinary output while exiting zero. Absence of a
terminal verdict is failure, not success.

#### Scenario: Exit zero with no terminal verdict fails
- **WHEN** a run exits with status zero and produced no terminal structured verdict
- **THEN** the gate fails the run

### Requirement: The gate reports which check failed

When the gate fails a run, its output SHALL identify which of the independent checks
failed and what it observed, rather than reporting only that verification failed.

#### Scenario: The failure is attributable
- **WHEN** the gate fails
- **THEN** its output names the failing check and the observation that caused it
