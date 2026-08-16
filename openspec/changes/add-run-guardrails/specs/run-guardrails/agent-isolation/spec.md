## Purpose

Keeps an agent run from silently inheriting the host's and the repository's own
configuration, so that what a run was told is what the run was configured with — expressed
as a policy other components consume, and recorded on every turn.

## ADDED Requirements

### Requirement: Isolation is a policy, and the default is isolated

The isolation posture SHALL be expressed as an explicit, typed configuration value whose
default is isolated. Running without isolation SHALL require an explicit opt-out; it is
never reached by omission, by a missing config file, or by a default.

#### Scenario: Absent configuration means isolated
- **WHEN** no isolation setting is supplied
- **THEN** the resolved policy is isolated

#### Scenario: Opting out is explicit
- **WHEN** a run executes without isolation
- **THEN** the configuration that produced it names the opt-out explicitly

### Requirement: The isolated posture excludes host and repository configuration

The isolated posture SHALL declare that the agent does not load the host's or the
repository's own agent configuration — instruction files, settings files, tool-server
configuration, or globally discovered skills — and instead receives its configuration
explicitly.

Repository-supplied configuration SHALL be treated as untrusted input to this decision
rather than as a source of settings, because it loads without a trust prompt in
non-interactive runs.

#### Scenario: The policy declares configuration explicitly
- **WHEN** the isolated policy is resolved
- **THEN** it names the settings and tool-server configuration to be supplied explicitly
- **AND** it does not defer to discovery of host or repository configuration

### Requirement: The policy never selects a mode incompatible with subscription auth

The isolation policy SHALL NOT select the executor's built-in bare mode.

**Reason, carried with the rule:** bare mode does not read the subscription OAuth
credential and therefore requires an API key. On a subscription, bare mode and
authentication are mutually exclusive — a policy that reaches for it produces a run that
cannot authenticate, and the failure surfaces as an unexplained refusal rather than as a
configuration error.

#### Scenario: Bare mode is never emitted
- **WHEN** any isolation policy is resolved, isolated or opted out
- **THEN** the resolved policy does not select bare mode

### Requirement: A preflight asserts a clean home directory

Before a run begins, a preflight check SHALL assert that the home directory the agent will
run under carries no user-level agent configuration.

The check SHALL report a boolean result. It SHALL NOT emit the home directory path, or any
absolute path derived from it, into output, logs, or records.

**Reason, carried with the rule:** an empty home directory on a fresh runner is true by
accident today. Asserting it makes the guarantee deliberate. The path is withheld because
this repository is public.

#### Scenario: A polluted home directory is caught before the run
- **WHEN** the preflight finds user-level agent configuration in the home directory
- **THEN** it reports failure and the run does not begin

#### Scenario: The assertion leaks no path
- **WHEN** the preflight reports either result
- **THEN** its output contains no absolute home-directory path

### Requirement: The preflight asserts the session cannot be suspended by a prompt

The preflight SHALL assert that the run executes in a mode where an approval prompt fails
and returns a denial rather than suspending the run to wait for a human.

**Reason, carried with the rule:** measurement on this fleet found that file edits and
commits run unattended without prompting — but that is a property of the current
permission configuration and session mode, not of the design. A mode change reopens the
hole silently, and a run suspended on a prompt nobody will answer is indistinguishable
from a hang. Asserting the property converts an incidental protection into a checked one.

This assertion does not remove the wall clock: a hang from a model call, a network wait,
or a tool that never returns is a different cause with the same symptom.

#### Scenario: An interactive-capable session is refused
- **WHEN** the preflight finds the run could be suspended awaiting human approval
- **THEN** it reports failure and the run does not begin

#### Scenario: The assertion is recorded, not assumed
- **WHEN** the preflight passes
- **THEN** the property was checked at preflight time rather than inferred from configuration read earlier

### Requirement: The posture is recorded on every turn

The isolation posture actually used SHALL be recorded on the turn record for that run.

**Reason, carried with the rule:** an opt-out that is not recorded is indistinguishable
later from a run that was isolated, and the two are not comparable evidence.

#### Scenario: An opted-out run is identifiable afterwards
- **WHEN** a run executes with isolation disabled
- **THEN** its turn record shows the run was not isolated

### Requirement: This capability stops at policy

This capability SHALL define and validate the isolation policy only. Translating the policy
into executor invocation arguments belongs to the executor wrapper and is out of scope
here.

#### Scenario: No executor is invoked
- **WHEN** the isolation policy is resolved and the preflight run
- **THEN** no agent executor is spawned by this capability
