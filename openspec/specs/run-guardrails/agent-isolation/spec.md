# run-guardrails/agent-isolation Specification

## Purpose
Keeps an agent run from silently inheriting the host's and the repository's own
configuration, so that what a run was told is what the run was configured with — expressed
as a policy other components consume, and recorded on every turn.
## Requirements
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

