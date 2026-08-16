# isolate-by-safe-mode

Corrects **D021**'s isolation mechanism and the `run-guardrails/agent-isolation` capability against
measurement. Measurements, in full: [exploration.md](exploration.md).

## Why

Denis's requirement: *"AI agents should be isolated: meaning in Claude Code SDK should not read our
container / host system CLAUDE.md and global skills. Or maybe we will make it a configuration
toggle."*

What shipped does not meet it. An agent run under the isolated posture reports the host's memory,
the host's skills and the repository's own skill and agent as loaded — from its own init event, so
this is the agent saying so rather than an inference. The fallback the design leaned on, an emptied
`$HOME`, is worse than ineffective: such a run cannot authenticate at all, and even if it could it
would hide the user's configuration while leaving the repository's untouched.

Both halves of the previous finding were wrong, and the reason they went unnoticed is the same in
both cases: **the code asserted the property instead of running it.** `home_is_clean` claimed an
empty home was the guarantee; nothing ever set a home and ran. An assertion is a claim about the
world; running it is the only thing that makes it a measurement.

## What Changes

- **The isolated posture becomes `--safe-mode --strict-mcp-config --disable-slash-commands`**, with
  `--permission-mode manual` unchanged. Measured to load no host configuration, no repository
  configuration, no skills and no commands, while authenticating normally on a subscription.
- **The isolated posture refuses an explicit tool-server config.** Safe mode ignores `--mcp-config`,
  measured three ways. A policy that is isolated and names one describes a run that would silently
  not have it, so it raises rather than emitting an argument that does nothing.
- **The opt-out posture becomes the compositional one.** `--settings`, `--mcp-config` and
  `--allowedTools` are emitted there, where they take effect, and each opt-out still carries a stated
  reason and is recorded on the turn.
- **The home preflight is inverted.** It asserted the home carried no user configuration; it now
  asserts the credential store is reachable from it. Same field, opposite polarity, and the inversion
  is the finding: the old assertion, satisfied, described a run that could not start.
- **`init.leaks` covers what enters context** — memory, tool servers, skills, commands — and a new
  `init.residue` records what registers without entering it.
- **`EMULATED` loses its false `cost_ceiling` entry.** The binary has `--max-budget-usd`. §7b rule 4
  invalidates a capability claim not checked against a pinned version, and that one was checked
  against nothing. Corrected, not wired — wiring it is a separate change.

## Acceptance

Integration receipts against the real binary, not unit tests:

1. **An isolated run in a hostile repository** — one carrying its own `CLAUDE.md`, skill and
   `.mcp.json`, all of which load under `-p` with no trust dialog — succeeds and reports no leaks
   from its own init event.
2. **The same run with the posture off reports leaks.** Without this control, an isolated run
   reporting nothing loaded is equally consistent with a host that had nothing to load.

## Non-goals

- **No filesystem boundary.** Under the isolated posture the agent still *can* read host files with
  the Read tool; the flags stop configuration being **loaded**, not being **reached**. Denis's
  requirement is about host instructions entering context, where they act as instructions. A file an
  agent went looking for is a different threat whose control is a filesystem boundary or a container,
  and there is nothing in the flag surface to chase it with. Recorded as residue with a named future
  control rather than as a caveat.
- **The bundled floor is not attacked.** Fifteen skills and five subagents ship inside the binary and
  no flag removes them. Not host configuration; not ours either.
- **The one host plugin is recorded, not failed on.** Safe mode registers a host-installed plugin
  that no flag unregisters — only a home the run cannot authenticate from. With commands disabled it
  contributes nothing to context.
- **No cost-ceiling wiring**, and **no rewrite of the classification path onto `terminal_reason`**.
  Both are separate changes with separate arguments.
- **No `--setting-sources ""` posture.** Kept in the record as the surgical second control, for a
  posture that wants the repository's conventions without the host's. Nothing needs it yet.

## Capabilities

### Modified Capabilities
- `run-guardrails/agent-isolation`: the isolated posture is defined by what a run is measured to
  load rather than by which arguments it was passed; the home preflight is inverted; the isolated
  posture is a floor that refuses additions.

### New Capabilities
- `claude-executor/isolation-verified`: an isolated run's posture is asserted from the agent's own
  init event, with leaks distinguished from recorded residue.

## Impact

- **`src/yosefactory/runtime/isolation.py`** — preflight inverted, `USER_CONFIG_MARKERS` and
  `home_is_clean` removed, an isolated policy naming a tool server now raises.
- **`src/yosefactory/executor/claude.py`** — the isolated branch of `build_argv`; `EMULATED`.
- **`src/yosefactory/executor/stream.py`** — `slash_commands` read, `leaks` widened, `residue` added.
- **Public repo** — no credential, token or home-rooted path reaches a record, a log or a test.
- **No new runtime dependencies.**
