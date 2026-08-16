# turn-publication Specification

## Purpose
Publishes what a turn committed so it is visible beyond the machine that ran it — the current branch,
pushed to an already-configured `origin`, on both repositories a turn touches, gated on the turn
having actually advanced.
## Requirements
### Requirement: Publication is gated on the turn's own outcome

Publication SHALL run only when the turn's outcome is `advanced`. For every other outcome,
publication SHALL be skipped, and the skip SHALL be distinguishable from a push that was attempted
and rejected.

**Reason, carried with the rule:** `blocked`'s workspace state carries no verification receipt — the
`done` gate is the only thing that inspects the workspace tree — so publishing on a `blocked` outcome
would publish on trust rather than on the evidence `advanced` requires.

#### Scenario: An advanced turn is published

- **WHEN** a turn's outcome is `advanced`
- **THEN** publication runs against the turn's places

#### Scenario: A failed turn publishes nothing

- **WHEN** a turn's outcome is `failed`
- **THEN** no push is attempted
- **AND** the skip is recorded as a gate decision, not as a rejected push

#### Scenario: A blocked turn publishes nothing

- **WHEN** a turn's outcome is `blocked`
- **THEN** no push is attempted, regardless of what the workspace tree currently holds

### Requirement: Publication runs strictly after the turn's own commit, never inside it

Publication SHALL begin only after the turn record has been written and committed. A failure to
publish SHALL NOT alter, delay, retry, or in any way affect the turn record already committed for
that run.

**Reason, carried with the rule:** the record is already a true statement about what the turn did by
the time publication runs. Folding publication into the turn's own transaction would make a network
failure capable of changing whether a locally true record gets written at all.

#### Scenario: A publication failure does not touch the turn record

- **WHEN** publication fails after a turn's record has been committed
- **THEN** the turn record is unchanged from what the turn itself produced
- **AND** the turn's return value to its caller is unaffected

### Requirement: The workspace publishes before the queue

When both repositories are published, the workspace SHALL be pushed before the queue.

**Reason, carried with the rule:** a published queue record can point at a workspace commit (via the
platform trailer or a named SHA). Publishing the queue first risks a public reference to a commit
that does not yet exist anywhere reachable; publishing the workspace first means the referent is
always public before any reference to it is.

#### Scenario: The workspace push happens first

- **WHEN** a turn publishes both places
- **THEN** the workspace push is attempted before the queue push

#### Scenario: A failed workspace push still allows the queue push to be attempted

- **WHEN** the workspace push is rejected
- **THEN** the queue push is still attempted
- **AND** both outcomes are reported

### Requirement: Publication never forces, tags, deletes, or creates a remote

Publication SHALL push only the current branch, by explicit name, to a remote named `origin` that is
already configured. Publication SHALL NOT force-push, push tags, delete a remote branch, or add,
change, or infer a remote that is not already configured.

#### Scenario: No remote configured is a skip, not a failure

- **WHEN** a repository has no `origin` remote configured
- **THEN** publication for that repository is skipped
- **AND** the skip is not reported as a rejected push

#### Scenario: A detached HEAD is refused rather than pushed under a synthetic name

- **WHEN** a repository's HEAD is detached at the point publication runs
- **THEN** publication for that repository is refused
- **AND** no push is attempted

#### Scenario: Force is never used

- **WHEN** a push would be rejected as a non-fast-forward
- **THEN** publication does not retry with force, and reports the rejection instead

### Requirement: A rejected push is reported once and not retried

When a push is rejected — non-fast-forward, unreachable remote, or any other failure — publication
SHALL report the rejection and SHALL NOT retry it automatically within the same turn.

**Reason, carried with the rule:** a push rejection means the remote moved or is unreachable, not
that the local state is wrong. Retrying blind into a remote that moved is how work gets overwritten
or duplicated; the correct response is a human or a later, separately-decided turn.

#### Scenario: A rejected push is reported

- **WHEN** a push is rejected for any reason
- **THEN** the rejection is reported with enough detail to identify which repository and why
- **AND** publication does not attempt that push again within the same turn

#### Scenario: A workspace push succeeding and a queue push failing are both visible

- **WHEN** the workspace push succeeds and the queue push is subsequently rejected
- **THEN** the successful push is not reported as a failure
- **AND** the rejected push is reported distinctly

### Requirement: Publication may be declined per place, and declined is not skipped

`Places` SHALL carry, independently for `workspace` and for `queue`, whether that place may be
published by this turn. When a place is not publishable, `publish` SHALL NOT invoke a push for it,
and SHALL report the place's status as `declined`.

`skipped` SHALL be reported only for a place that was publishable but had no `origin` remote
configured. `declined` SHALL be reported only for a place the caller marked not publishable.
Neither status SHALL be produced by the other's cause, and a place that is both not publishable and
has no `origin` configured SHALL still report `declined` — the caller's instruction is checked first
and unconditionally, so `push_repo` is never invoked for a declined place and its own remote state is
never consulted.

Absent an explicit choice, both places SHALL be publishable — this requirement changes whether
publication can be declined, not whether it happens by default ([[D022]] grants push; declining is an
opt-out a caller states, not a new default).

#### Scenario: A declined place is not pushed

- **WHEN** a turn advances and `workspace` is marked not publishable
- **THEN** no push is attempted against the workspace
- **AND** its publication result reports `declined`

#### Scenario: Declined and skipped are never conflated

- **WHEN** a place is marked not publishable and also has a real, reachable `origin` configured
- **THEN** its publication result reports `declined`, never `skipped` or `pushed`

#### Scenario: An unstated choice publishes, exactly as before this requirement existed

- **WHEN** a turn's `Places` supplies no opinion on either place's publishability
- **THEN** both places publish exactly as `turn-publication`'s other requirements already specify

