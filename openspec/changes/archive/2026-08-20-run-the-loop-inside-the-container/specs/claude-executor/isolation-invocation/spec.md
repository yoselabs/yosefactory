## ADDED Requirements

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
