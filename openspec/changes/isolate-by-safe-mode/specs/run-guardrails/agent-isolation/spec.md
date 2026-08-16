# run-guardrails/agent-isolation Specification

## MODIFIED Requirements

### Requirement: A preflight asserts a clean home directory

Before a run begins, a preflight check SHALL assert that the home directory the agent will run under
is one the executor's credential store can be reached from.

The check SHALL report a boolean result and a reason code. It SHALL NOT emit the home directory
path, or any absolute path derived from it, into output, logs, or records.

**Reason, carried with the rule:** this requirement previously asserted the opposite — that the home
carried no user-level agent configuration — on the belief that an emptied home was the isolation
mechanism. Measured, an emptied home does not isolate: the subscription credential lives in the host
keychain beneath the home directory, so a run given a fresh home reports that it is not logged in and
performs no work. An emptied home also leaves repository-level configuration entirely intact, so it
never covered more than one of three leak surfaces. The assertion was satisfied for as long as it
was never executed.

#### Scenario: A polluted home directory is caught before the run
- **WHEN** the preflight finds no credential store beneath the home directory
- **THEN** it reports failure and the run does not begin

#### Scenario: The assertion leaks no path
- **WHEN** the preflight reports either result
- **THEN** its output contains no absolute home-directory path

### Requirement: The isolated posture excludes host and repository configuration

The isolated posture SHALL be defined by the configuration an agent run is measured not to load, and
SHALL be verified from the agent's own startup report rather than from the arguments it was given.

A run declared isolated whose startup report names host or repository instruction files, tool
servers, skills, or commands SHALL fail rather than proceed.

**Reason, carried with the rule:** the previous posture named arguments and was credited with their
intent. An agent run under them reported the host's memory, the host's skills, and the repository's
own skill and agent as loaded. Arguments express an intent; the startup report is the run stating
what it actually has, and only one of the two can disagree with reality.

#### Scenario: A run that loaded host configuration does not pass as isolated
- **WHEN** an isolated run's startup report names loaded instruction files, tool servers, skills, or commands
- **THEN** the run is reported as failed and names what it loaded

#### Scenario: The verification has a control
- **WHEN** the isolated posture is verified
- **THEN** an equivalent run with the posture disabled is shown to load host configuration

#### Scenario: The policy declares configuration explicitly
- **WHEN** the isolated policy is resolved
- **THEN** it does not defer to discovery of host or repository configuration — nothing it was not
  handed explicitly reaches the run, and construction refuses an explicit tool-server or settings
  config the isolated posture cannot actually honour

## ADDED Requirements

### Requirement: The isolated posture is a floor and admits no additions

The isolated posture SHALL NOT accept an explicit tool-server configuration. A policy that is
isolated and names one SHALL be refused when it is constructed.

Explicitly supplied settings, tool-server configuration, and tool allowances SHALL be expressed in
the opted-out posture, where they take effect.

**Reason, carried with the rule:** measured, the executor's safe mode ignores an explicitly supplied
tool-server configuration — with and without strict tool-server handling, and with and without
commands disabled. Emitting the argument anyway would produce a run that quietly lacks what it was
told to have, which is the failure this capability exists to prevent.

#### Scenario: An isolated policy naming a tool server is refused
- **WHEN** a policy is constructed as isolated and names a tool-server configuration
- **THEN** construction fails with a stated reason

#### Scenario: An opted-out policy may name one
- **WHEN** a policy opts out with a stated reason and names a tool-server configuration
- **THEN** it is accepted and the configuration is supplied to the run

### Requirement: Residue is recorded rather than treated as a breach

Host installations that register under the isolated posture without contributing to the agent's
context SHALL be recorded distinctly from configuration that enters context, and SHALL NOT by
themselves fail a run.

**Reason, carried with the rule:** measured, one host-installed plugin registers under every
isolated posture that can authenticate, and no argument unregisters it. With commands disabled it
supplies no skills and no commands, so it places nothing in front of the model. Failing on it would
fail every isolated run; dropping it silently would lose the only record that the floor is not zero,
and a residue nobody writes down is a residue nobody re-measures when the executor moves.

#### Scenario: A registered plugin contributing nothing does not fail the run
- **WHEN** an isolated run's startup report names a registered plugin but no skills and no commands
- **THEN** the run proceeds and the registration is recorded as residue

### Requirement: Configuration isolation is bounded, and the boundary is stated

This capability SHALL state that it prevents host and repository configuration from being **loaded**
into a run, and that it does not prevent an agent from **reaching** host files through its own tools.

**Reason, carried with the rule:** the operative harm is host instructions entering an agent's
context, where they act as instructions. A file the agent chose to read is a different threat whose
control is a filesystem boundary, and no argument in the executor's surface provides one — measured:
under the strongest isolated posture the agent read the host's user instruction file on request.
Recording the boundary keeps it a known residue with a named future control rather than an assumed
guarantee.

#### Scenario: The boundary is recorded rather than implied
- **WHEN** the isolated posture is described
- **THEN** it states that reachability through tools is out of its scope
