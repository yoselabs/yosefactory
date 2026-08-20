## Purpose

Defines what isolation posture the loop's unattended (scheduled/container) entrypoint uses by
default, and states plainly which part of "the agent cannot reach anything outside its workspace"
is a property of container mount topology and which part remains an application policy choice.

## ADDED Requirements

### Requirement: The unattended entrypoint does not default to a posture that denies its own tool calls

`scheduled_main` (the entrypoint a scheduler or a container invokes — never a person) SHALL NOT
default to a posture that requires human approval for tool calls. The interactive entrypoint
(`main`, called directly, `unattended=False`) is unaffected and keeps its existing default.

**Reason, carried with the rule:** the posture correct for a person at a keyboard on their own
laptop is not the posture correct for a process nobody is watching. A posture that requires human
approval for tool calls, run with no human present, does not produce a safer turn — it produces a
turn that does nothing and ends `needs_approval`, indistinguishable from a hang until someone reads
the record.

#### Scenario: The unattended entrypoint runs real tool calls without a human answering a prompt
- **WHEN** `scheduled_main` invokes a turn
- **THEN** the turn's tool calls are not denied for lack of human approval

#### Scenario: The interactive entrypoint is unchanged
- **WHEN** `main` is invoked directly, not through `scheduled_main`
- **THEN** its isolation posture default is the same one it used before this change

### Requirement: The boundary against reaching outside the workspace is stated as topology or policy, per mechanism

For each way an unattended run is kept from reaching something outside its intended workspace, the
design record SHALL state whether that boundary is enforced by container mount topology (nothing
else is mounted into the container, so there is nothing there to reach) or by application policy
(a flag or configuration choice that could, in principle, be misconfigured or omitted).

**Reason, carried with the rule:** the two are not the same guarantee. A topology boundary holds
even if every policy choice in the process is wrong, because the unreachable thing is not present
in the container's filesystem at all. A policy boundary holds only as long as the flag is set
correctly on every invocation. Conflating them lets a policy-only protection be reported with the
confidence that belongs to a topology-only one.

#### Scenario: A topology boundary is verified by a real attempt, not by describing the mount
- **WHEN** a run inside the container attempts to read or write a path outside its mounted
  workspace (a host path, another project, the operator's credential store)
- **THEN** the attempt fails because the path does not exist inside the container, and the record
  of this change quotes the actual attempt and its failure rather than only asserting the mount
  layout

#### Scenario: A policy boundary is named as policy, not conflated with topology
- **WHEN** the record states that tool calls inside the workspace are not gated by human approval
- **THEN** it is named as a policy choice (the permission mode selected), not as a property the
  container's mounts provide

### Requirement: The container never mounts the operator's other projects or credential store into an unattended run

The compose configuration used for an unattended/container run SHALL NOT bind-mount any path
outside the yosefactory repository and its designated workspace, and SHALL NOT mount the operator's
host credential store (keychain, `~/.claude` host state, SSH keys, `gh` login).

#### Scenario: Nothing outside the repository is mounted
- **WHEN** the compose configuration used for the receipt run is inspected
- **THEN** its volumes name only the yosefactory repository (and, where the two are kept separate,
  a workspace path within it) — no other host directory, and no host credential path
