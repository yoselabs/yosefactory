# run-guardrails/agent-isolation Specification

## MODIFIED Requirements

### Requirement: The isolated posture is a floor and admits no additions

The isolated posture SHALL NOT accept an explicit tool-server configuration, and SHALL NOT accept an
explicit `--settings` argument that sets an `env` entry. A policy that is isolated and names either
SHALL be refused when it is constructed.

Explicitly supplied settings, tool-server configuration, and tool allowances SHALL be expressed in
the opted-out posture, where they take effect.

**Reason, carried with the rule:** measured, the executor's safe mode ignores an explicitly supplied
tool-server configuration. Separately measured for this change: an explicit `--settings` env entry
survives safe mode and reaches the run, while the same mechanism's `hooks` entry does not — safe
mode's suppression is category-based (`CLAUDE.md`, skills, plugins, hooks, MCP servers, commands),
not a blanket rejection of `--settings`. A caller passing `--settings` with an isolated policy and
expecting silence would get a working env var instead, which is the same failure shape the
tool-server refusal already exists to prevent.

#### Scenario: An isolated policy naming a tool server is refused
- **WHEN** a policy is constructed as isolated and names a tool-server configuration
- **THEN** construction fails with a stated reason

#### Scenario: An isolated policy naming a `--settings` env entry is refused
- **WHEN** a policy is constructed as isolated and names an explicit `--settings` argument setting `env`
- **THEN** construction fails with a stated reason

#### Scenario: An opted-out policy may name one
- **WHEN** a policy opts out with a stated reason and names a tool-server configuration or an
  explicit `--settings` argument
- **THEN** it is accepted and the configuration is supplied to the run

### Requirement: Residue is recorded rather than treated as a breach

Host installations that register under an isolation posture without contributing to the agent's
context SHALL be recorded distinctly from configuration that enters context, and SHALL NOT by
themselves fail a run.

**Reason, carried with the rule:** measured, one host-installed plugin registers under every isolated
posture that can authenticate, and no argument unregisters it. Separately measured for this change:
account-level MCP connectors (OAuth-registered servers, distinct from `.mcp.json`/`settings.json`
entries) register under every `--setting-sources` value tested, including the empty string, and are
not reachable through that flag at all. Both are floors, not breaches, and both are the kind of fact
that stops being true silently if the executor changes underneath this code — recording them is what
makes a future re-measurement possible.

#### Scenario: A registered plugin contributing nothing does not fail the run
- **WHEN** an isolated run's startup report names a registered plugin but no skills and no commands
- **THEN** the run proceeds and the registration is recorded as residue

#### Scenario: An account-connector MCP server does not fail a workspace-scoped run
- **WHEN** a workspace-scoped run's startup report names an account-level MCP connector that was not
  declared by the workspace's `.mcp.json`
- **THEN** the run proceeds and the connector is recorded as residue, distinct from the workspace's
  own declared servers

## ADDED Requirements

### Requirement: A workspace-scoped posture admits workspace configuration while excluding host configuration

A `workspace_scoped` posture SHALL exist, distinct from `isolated` and `opted-out`. Under it, a run
SHALL load the working repository's own `CLAUDE.md`, `.claude/settings.json`,
`.claude/settings.local.json`, `.claude/skills/`, and `.mcp.json`, and SHALL NOT load the host user's
`~/.claude/CLAUDE.md`, host user-level skills or plugins, or host-configured
(`settings.json`-declared) MCP servers.

It SHALL be verified the same way `isolated` is: from the agent's own `system|init` event for
skills, plugins, and MCP servers, and from a canary turn for memory, since `memory_paths` never lists
a repository `CLAUDE.md` under any posture.

**Reason, carried with the rule:** the platform now acts on repositories that are not its own. The
target repository's own conventions — commit rules, ADR discipline, architecture-guard registry —
are exactly what an agent working there needs, and the previously all-or-nothing isolated posture
hid them. Measured: `--setting-sources {user,project,local}` gates host-level and workspace-level
configuration independently, confirmed on five surfaces (memory, skills, MCP, hooks, env) with
canary turns that rely on a side effect, not the model's self-report.

#### Scenario: A workspace-scoped run admits the repository's own configuration
- **WHEN** a workspace-scoped run starts in a repository carrying its own `CLAUDE.md`, skill, hook,
  and `.mcp.json` server
- **THEN** the canary turn confirms the repository's `CLAUDE.md` token is present, the skill and MCP
  server appear in the startup report, and the repository's hook fires on a matching tool call

#### Scenario: A workspace-scoped run excludes the host's own configuration
- **WHEN** the same run is checked against the host's user-level `CLAUDE.md` token, skills, and
  `settings.json`-declared MCP servers
- **THEN** the canary turn confirms the host token is absent and the startup report does not list the
  host's user-level skills, plugins, or MCP servers

### Requirement: The workspace-scoped and isolated postures are mutually exclusive

A policy SHALL NOT request both `isolated` and `workspace_scoped`. Construction SHALL refuse the
combination with a stated reason.

**Reason, carried with the rule:** measured, `--safe-mode` overrides `--setting-sources` to zero
regardless of the value passed — `--safe-mode --setting-sources project` reports no repository
memory, no repository skill, and no repository MCP server, identically to `--safe-mode` alone. The
two mechanisms do not compose; a policy naming both would silently get only the isolated behavior,
which is the same silent-mismatch failure the existing tool-server refusal exists to prevent.

#### Scenario: A policy naming both postures is refused
- **WHEN** a policy is constructed requesting both `isolated` and `workspace_scoped`
- **THEN** construction fails with a stated reason naming the conflict
