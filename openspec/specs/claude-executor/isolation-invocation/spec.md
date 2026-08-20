# claude-executor/isolation-invocation Specification

## Purpose
Carries the isolation posture from policy into a real invocation, and — the load-bearing half —
requires an isolated run to be *verified* isolated from what the agent reports loading, rather
than assumed isolated from the arguments it was given.
## Requirements
### Requirement: The invocation carries the posture; the executor does not choose it

The isolation posture SHALL be supplied to the executor by its caller. The executor SHALL NOT
select, infer, or override it.

Resolving the posture, its default, and its opt-out belong to the isolation policy and are
specified there. This capability begins where that one stops.

#### Scenario: No posture is chosen inside the executor
- **WHEN** an executor is invoked
- **THEN** the posture it runs under is the one it was handed

#### Scenario: The posture actually used is reportable
- **WHEN** a run completes under any posture
- **THEN** the executor reports which posture it ran under, so the turn record can carry it

### Requirement: An isolated run is verified from the agent's own startup report

An executor SHALL determine whether a run was actually isolated by reading what the agent
reports having loaded at startup — its instruction sources, tool servers, skills and plugins —
and SHALL NOT determine it from the arguments the executor passed.

An isolated run that reports having loaded any of them SHALL fail before doing work, and the
failure SHALL name the leak set it observed.

**Reason, carried with the rule, and it is measured rather than argued:** a run was observed
loading host skills, memory and plugins while every argument believed to isolate it was passed.
Arguments express an intent; the startup report is the agent stating what it did. Only the
second one can disagree with reality, and a breach that nothing checks is a breach nobody sees.

#### Scenario: A leak fails the run rather than being logged
- **WHEN** a run declared isolated reports loading host or repository configuration
- **THEN** the run fails and does not proceed to do work

#### Scenario: The failure says what leaked
- **WHEN** an isolation breach is detected
- **THEN** the failure names which categories leaked and how many entries each carried

#### Scenario: Passing the right arguments is not evidence of isolation
- **WHEN** a run is invoked with arguments intended to isolate it
- **THEN** isolation is still asserted from the startup report before the run is allowed to continue

### Requirement: This capability names no specific invocation arguments

The contract SHALL be expressed in terms of the posture and its verification, and SHALL NOT
enumerate the executor's command-line arguments, flags, or configuration file names.

**Reason, carried with the rule:** the argument set that isolates a run has already changed once
under measurement, and the contract must survive that. A spec naming flags is false on the next
binary release; a spec requiring the run to report its own leak set stays true across every
flag change — and it is the only form of the rule that would have caught the breach above.

#### Scenario: A changed flag set does not change the contract
- **WHEN** the arguments required to isolate a run change
- **THEN** this capability is unchanged and the verification requirement still holds

### Requirement: The executor never emits a mode that cannot authenticate

The executor SHALL NOT invoke the agent in a mode that is unable to read the operator's
subscription credential, under any posture.

**Reason, carried with the rule:** such a mode buys isolation by making the run unable to
authenticate at all, and the failure surfaces as an unexplained refusal rather than as a
configuration error. The policy already forbids selecting it; this forbids emitting it.

#### Scenario: Isolation is never bought by breaking authentication
- **WHEN** an executor builds an invocation under the isolated posture
- **THEN** the invocation does not select a mode incompatible with subscription authentication

### Requirement: A workspace-scoped invocation does not require human approval for tool calls

When the isolation posture is `workspace_scoped`, the executor SHALL build an invocation whose
permission mode does not require a human to approve tool calls.

**Reason, carried with the rule:** `workspace_scoped` exists so the platform can act on a real
repository under the repository's own conventions, unattended. An invocation that admits the
repository's configuration but still requires human approval for every tool call is not usable
unattended — it fails exactly the way the previous, unconditional `isolated` default failed,
for a different reason. This capability already owns translating posture into invocation
arguments (`claude-executor/isolation-invocation`'s own Purpose); this requirement completes that
translation for the one posture that previously emitted none.

#### Scenario: A workspace-scoped invocation's tool calls are not gated on approval
- **WHEN** the executor builds an invocation under the `workspace_scoped` posture
- **THEN** the resulting invocation's permission mode does not deny or suspend a tool call for
  lack of human approval

#### Scenario: The isolated posture is unchanged
- **WHEN** the executor builds an invocation under the `isolated` posture
- **THEN** its permission mode is exactly as it was before this change

