# containerized-loop/unattended-publication-posture Specification

## Purpose
TBD - created by archiving change pin-the-executor-and-close-the-push-grant. Update Purpose after archive.
## Requirements
### Requirement: The unattended entrypoint declines publication by default

`scheduled_main` (the entrypoint a scheduler or a container invokes — never a person) SHALL, absent
an explicit instruction otherwise, run turns that commit locally and do not push. The interactive
entrypoint (`main`, called directly, `unattended=False`) is unaffected and keeps publishing exactly
as it did before this capability existed.

**Reason, carried with the rule:** D022 §2 granted push for a turn a human is watching. An
unattended run committing dozens of commits — including a history rewrite — with nobody watching is
the case that grant was never written for; the only reason a push has not already reached a shared
remote by accident is that no credential happens to be present, which is topology, not a decision.

#### Scenario: An unattended turn that advances does not push
- **WHEN** `scheduled_main` runs a turn that advances
- **THEN** no push is attempted for either place the turn touches
- **AND** the turn's commits remain local, ahead of the remote, exactly as it left them

#### Scenario: The interactive entrypoint is unaffected
- **WHEN** `main` is invoked directly, not through `scheduled_main`
- **THEN** publication runs exactly as it did before this capability existed

### Requirement: A declined push is reported as declined, not conflated with no-remote or with a failed push

An unattended turn that does not publish SHALL report each place's publication result as
`declined`, using the same status `turn-publication`'s per-place decline mechanism already defines,
distinct from `skipped` (no remote configured) and from `rejected` (a push was attempted and
refused).

**Reason, carried with the rule:** a structural failure to push (no credential, no network) and a
decision not to push look identical from the outside unless the record says which one happened. A
future container that does carry a push credential must not have its first successful unattended
push misread as "it was already declining, same as before."

#### Scenario: A declined unattended push is distinguishable from a structural failure
- **WHEN** an unattended turn advances and publication is not attempted because the entrypoint
  declined it
- **THEN** the publication result reports `declined`
- **AND** this is distinguishable from a result that reports `skipped` or `rejected`

### Requirement: The grant reopens only through an explicit instruction on the unattended entrypoint's own invocation

The unattended entrypoint SHALL provide an explicit way to re-enable publication for a given
invocation, and SHALL NOT re-enable it through any implicit signal (an environment variable read
for another purpose, the mere presence of a push credential, or a change to the interactive
entrypoint's own behaviour).

**Reason, carried with the rule:** a grant that reopens implicitly is a grant that reopens by
accident. Requiring it on the invocation itself keeps the decision visible in the same place an
operator already reads before changing how the loop is run.

#### Scenario: Reopening the grant requires an explicit instruction on that invocation
- **WHEN** an operator wants an unattended run to publish
- **THEN** they state that explicitly on the entrypoint's own invocation
- **AND** no other mechanism (a credential becoming available, an environment variable set for a
  different purpose) causes publication to resume on its own

