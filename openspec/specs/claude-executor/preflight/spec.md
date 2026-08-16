# claude-executor/preflight Specification

## Purpose
A once-per-job check that fails a job in seconds for a reason it can name — an expired
credential, a moved binary — instead of twenty minutes in, where the same causes are
indistinguishable from a badly framed task.
## Requirements
### Requirement: The preflight runs once per job, never per turn

An executor SHALL expose a preflight check intended to run once before a job's first run, and
the check SHALL NOT be required before every turn.

**Reason, carried with the rule:** the check costs a real invocation, measured at roughly a
quarter of a dollar on a cold cache. That is worth paying once to fail fast, and is not worth
paying on every turn of a long job.

#### Scenario: A job checks once
- **WHEN** a job performs many runs
- **THEN** the preflight is required only before the first of them

#### Scenario: A failed preflight stops the job
- **WHEN** the preflight fails for any reason
- **THEN** the job does not proceed to its first run

### Requirement: Credential validity is checked, never assumed

The preflight SHALL establish that the agent can actually authenticate, by performing a minimal
real invocation rather than by inspecting configuration.

**Reason, carried with the rule:** a silently expired credential is otherwise
indistinguishable from a badly framed task — both produce a run that does nothing useful and
reports no clear cause. Treating expiry as unknown and checking it is what turns a twenty-minute
mystery into a five-second refusal.

#### Scenario: An expired credential is caught before the work starts
- **WHEN** the agent's credential has expired
- **THEN** the preflight fails naming authentication, and no work run is started

#### Scenario: Configuration inspection is not the check
- **WHEN** the preflight passes
- **THEN** it passed because an invocation authenticated, not because a configuration file was present

### Requirement: Capabilities belong to the binary, and the version is pinned

The preflight SHALL resolve the agent binary's own reported version and SHALL fail when it does
not match the version the executor's behaviour was measured against.

The version SHALL be resolved by asking the binary, never inferred from a package pin, which
describes a different artifact.

**Reason, carried with the rule:** a capability claim without a passing check against a pinned
version is invalid by construction. A receipt taken against a different binary is not this
receipt.

#### Scenario: A moved binary fails with a named reason
- **WHEN** the installed agent reports a version other than the pinned one
- **THEN** the preflight fails naming a version mismatch, distinct from an authentication failure

#### Scenario: The version comes from the binary
- **WHEN** the preflight resolves the version
- **THEN** it is the version the installed binary reports about itself

### Requirement: An absent capability must declare its emulation or registration fails

Where an executor declares a capability absent, it SHALL also declare how the harness supplies
that behaviour instead. An executor declaring an absent capability with no stated emulation
SHALL fail registration.

**Reason, carried with the rule:** this is the clause that survives deferring a full capability
map until a second executor exists. Without it, "we will add cost limits later" ships as an
absent capability nobody notices; with it, absence has to be paid for at registration time.

#### Scenario: Absence without emulation is refused
- **WHEN** an executor declares a capability absent and states no harness-side emulation
- **THEN** it fails registration rather than being usable with a silent gap

#### Scenario: A declared emulation is accepted
- **WHEN** an executor declares a capability absent and names how the harness supplies it
- **THEN** registration succeeds

