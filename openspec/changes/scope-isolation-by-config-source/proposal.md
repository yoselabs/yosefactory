# scope-isolation-by-config-source

Adds a third isolation posture to `run-guardrails/agent-isolation`, on top of what
`isolate-by-safe-mode` established. Measurements, in full: [exploration.md](exploration.md).

## Why

Denis's original requirement (`isolate-by-safe-mode`) was host isolation for the platform acting on
its own repo. That got the fully-isolated posture right. But the platform can now act on a repository
that is not its own — and there, host config is still hostile while **workspace config (the target
repo's own `CLAUDE.md`, `.claude/`, `.mcp.json`) is required**: it is the target repo's commit-message
rules, ADR discipline, architecture-guard registry. One earlier run suspended over a commit-convention
rule that lived in the target repo's own documentation and was never visible because the run used the
all-or-nothing isolated posture.

Measured: this is not a false choice. `--setting-sources {user,project,local}` gates host-level and
workspace-level config **separately**, on five distinct surfaces (memory, skills, MCP, hooks, env),
confirmed by canary turns with real side effects, not by argument inspection. It is a genuinely
different mechanism from `--safe-mode`, not a variant of it, and the two do not compose — safe mode
overrides it to zero regardless of the value passed.

## What Changes

- **A named `workspace-scoped` posture is added**, alongside the existing `isolated` and `opted-out`
  postures. It runs with `--setting-sources project,local` and no `--safe-mode`. Measured to admit the
  repository's `CLAUDE.md`, its `.claude/settings.json` and `.claude/settings.local.json` (env and
  hooks), its `.claude/skills/`, and its `.mcp.json`, while excluding the host's `~/.claude/CLAUDE.md`,
  the host's user-level skills and plugins, and host-configured (`settings.json`-level) MCP servers.
- **`workspace-scoped` and `isolated` are mutually exclusive by construction**, not by convention.
  Safe mode zeroes `--setting-sources` regardless of its value (measured); a policy MUST NOT request
  both, and construction refuses the combination the same way `isolated` already refuses an explicit
  tool-server config.
- **Verification extends the same way `isolated` is verified**: from the agent's own `system|init`
  event plus a canary turn for memory (init's `memory_paths` never lists a repository `CLAUDE.md`,
  same limitation as before), not from the arguments passed.
- **A residue class specific to this posture is recorded**: account-level MCP connectors
  (OAuth-registered servers, distinct from `.mcp.json`/`settings.json` entries) are not gated by
  `--setting-sources` at all and appear under every value tested, including `""`. A
  `workspace-scoped` run that believes it excludes "host MCP" is wrong about this specific class.
  Recorded as residue per the existing residue mechanism (`isolate-by-safe-mode`'s
  `init.residue`/`init.leaks` split), not failed on — it registers without contributing tool-call
  surface the same shape as the one host plugin already recorded as residue for `isolated`.
- **`--settings` under `isolated` is corrected, narrowly.** Measured: an explicit `--settings` env
  entry survives `--safe-mode`; an explicit `--settings` hook entry does not. `isolated`'s refusal
  rule (currently scoped to an explicit tool-server config) is extended to refuse an explicit
  `--settings` argument that sets `env`, for the same reason `--mcp-config` is refused under
  `isolated`: it would silently apply rather than silently not apply, and the two look identical from
  outside. `workspace-scoped` is unaffected by this — it does not use `--safe-mode`, so nothing about
  it is suppressed by category the way `isolated` is.

## Acceptance

Integration receipts against the real binary:

1. **A `workspace-scoped` run in the hostile fixture** admits the repo's `CLAUDE.md`, skill, hook,
   and `.mcp.json` server, and excludes the host's `CLAUDE.md`, host skills/plugins, and host
   `settings.json`-level MCP servers — verified by canary turn for memory, by init event for the rest.
2. **The account-connector residue is present and recorded**, not silently dropped and not failed on.
3. **A policy requesting both `isolated` and `workspace-scoped` is refused at construction**, with a
   stated reason, the same shape as the existing tool-server refusal.
4. **An `isolated` policy carrying an explicit `--settings` env entry is refused at construction.**

## Non-goals

- **No filesystem boundary**, same statement as `isolate-by-safe-mode`: `workspace-scoped` stops
  configuration being *loaded*, not being *reached*. An agent can still `Read` a host file if it goes
  looking.
- **No attempt to gate account-connector MCP servers.** Not reachable through `--setting-sources`;
  recorded as residue with a named future control (likely account-level, outside this executor's flag
  surface), not chased here.
- **No change to the `isolated` posture's own definition** beyond the narrow `--settings`-env
  refusal above. `isolated` still means what `isolate-by-safe-mode` measured it to mean.
- **`CLAUDE_CONFIG_DIR` combined with `--setting-sources` is not proposed or measured.** Left as
  unmeasured per exploration.md; a future change if a use case needs it.
- **`--settings` under safe mode for keys other than `env`/`hooks`** (`permissions`, `model`, …) is
  unmeasured and this proposal does not claim anything about them.

## Capabilities

### Modified Capabilities
- `run-guardrails/agent-isolation`: a third posture (`workspace-scoped`) is defined, mutually
  exclusive with `isolated`; `isolated`'s refusal rule widens to cover an explicit `--settings` env
  entry; a new residue class (account-connector MCP) is named.

## Impact

- **`src/yosefactory/runtime/isolation.py`** — a `workspace_scoped` branch alongside `isolated`;
  construction refuses `isolated + workspace_scoped` and `isolated` + `--settings` env.
- **`src/yosefactory/executor/claude.py`** — `build_argv` gains the `--setting-sources
  project,local` branch.
- **`src/yosefactory/executor/stream.py`** — the account-connector residue class added to
  `init.residue`.
- **No new runtime dependencies.**
- **Not applied by this dispatch.** Explore + propose only, per the director's instruction; awaiting
  release before `apply`.
