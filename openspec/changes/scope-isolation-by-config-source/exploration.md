# Exploration — can host config and workspace config be excluded independently?

Measured 2026-08-16 by YF-8, against `claude 2.1.225` on macOS, subscription auth. Builds on
[isolate-by-safe-mode/exploration.md](../isolate-by-safe-mode/exploration.md) (not yet archived) —
that change measured the fully-isolated posture (`--safe-mode --strict-mcp-config
--disable-slash-commands`). This one measures a different question: with the platform now able to
act on a repository that is not its own, host config is still hostile but **workspace config is now
required** — the target repo's own conventions are what an agent working there needs. Can the two be
switched independently, or is isolation still all-or-nothing?

## Answer, stated first

**Yes — independently controllable, via `--setting-sources`, but only outside `--safe-mode`.**
`--safe-mode` remains a floor that zeroes both axes together (confirmed below, not assumed from the
prior change). `--setting-sources {user,project,local}` is a real second mechanism, orthogonal to
`--safe-mode`, that gates host config and workspace config separately and was measured to do so on
five distinct surfaces: memory (`CLAUDE.md`), skills, MCP servers (`.mcp.json`), hooks, and env vars.

## Instruments

Same two as the prior change, for the same reason: `memory_paths` in the `system|init` event never
lists a repository `CLAUDE.md`, so init alone cannot answer the memory question.

1. **init probe** — `claude -p hi --output-format stream-json --verbose <flags>`, read until
   `system|init`. Used for skills/plugins/mcp counts.
2. **canary turn** — a real `-p` turn, `--tools ""` for memory presence (the model cannot go read a
   file); `--tools "Bash" --permission-mode bypassPermissions` for env/hook presence, where the
   signal is a side effect (`printenv`, a marker file written by a hook), not the model's say-so.

Fixture — a scratch git repo at `/tmp/yf8-fixture`, outside any tracked repo, hostile on purpose:

```
CLAUDE.md                        token YF8_REPO_CANARY_MEMORY_TOKEN_9f3a
.claude/settings.json            env YF8_REPO_CANARY_ENV=loaded, PreToolUse hook -> marker file
.claude/settings.local.json      env YF8_LOCAL_CANARY_ENV=loaded
.claude/skills/yf8-canary/       a skill
.mcp.json                        server "yf8-canary-mcp"
```

Host canary: the token `global-claude.md`, present in `~/.claude/CLAUDE.md` (same one the prior
change used). Host also carries a real `PreToolUse`/`PostToolUse`/... hook (an Orca integration
script) and several account-level MCP connectors (`claude.ai Gmail`, `Google Drive`, etc.) —
unplanned but useful, see §4.

## 1. `--setting-sources` is a real, granular admit-list

`--help`: *"Comma-separated list of setting sources to load (user, project, local)."* Measured
against all three values, individually and combined, on five surfaces:

```
   posture              repoMD  userMD  repo-skill  repo-mcp  repo-env  repo-hook
   (no flag, baseline)  yes     yes     yes         yes       —         —
   sources=project       yes     no     yes(20 skills) yes    loaded    fired
   sources=user          no      yes    no(40 skills)  no     unset     did not fire
   sources=""            no      no     no(19,floor)   no      —        —
   sources=local          —       —      —              —      LOCAL only, not repo-env
   sources=project,local  —       —      —              —      both env vars present
```

- `project` and `user` are exact mirror images on memory (`REPO_MEMORY`/`USER_MEMORY` canary turn),
  confirmed both directions.
- `project` alone: skills_count 20 (bundled floor ~19 + the repo skill), host plugins (`skill-creator`,
  `k-my`) absent, host-configured MCP (`qmd`) absent, repo `.mcp.json` server present.
- `user` alone: skills_count 40 (host's 41 minus the one repo skill), host plugins present, host MCP
  (`qmd`, `a2web`) present, repo `.mcp.json` server **absent**.
- `local` is a distinct scope from `project` — `.claude/settings.local.json` env var loaded only when
  `local` is in the list; `.claude/settings.json` env var loaded only when `project` is; the two
  compose under `project,local`.
- **Hooks are gated identically to env**, confirmed behaviorally, not inferred: a repo `PreToolUse`
  hook (writes a marker file) fires under `sources=project`, does not fire under `sources=user`. Same
  `.claude/settings.json` object, same gate, both keys (`env`, `hooks`) tested directly.

**So the toggle exists and is granular**, not binary the way `--safe-mode` is. It admits exactly the
combination "workspace files (`project`+`local`), not the host's user-level files (`user`)."

## 2. `--safe-mode` still overrides it — confirmed, not assumed

```
--safe-mode --setting-sources project   →  memory_paths None, skills 19 (floor), mcp_servers [],
                                            REPO_MEMORY=no, USER_MEMORY=no
```

Both axes zeroed together. This directly extends the prior change's finding ("safe mode is a floor,
not a base to build on" — explicit `--mcp-config` re-admission does not survive it) to
`--setting-sources` as well: **safe mode is not a base either axis can be dialed from.** The two
mechanisms do not compose; whichever fires, fires alone.

## 3. `--settings` under `--safe-mode`: punches through, unevenly — the item left unmeasured last time

Explicit `--settings '<json>'` was untested under safe mode in the prior change. Measured now, on two
of its keys:

```
--safe-mode --settings '{"env":{"X":"present"}}'                     →  env var IS set (leaks through)
--safe-mode --settings '{"hooks":{"PreToolUse":[...marker...]}}'     →  hook does NOT fire (blocked)
```

Sanity check: the same hook JSON via `--settings` **without** `--safe-mode` fires normally, so this
is safe mode's doing, not a malformed hook spec.

**Safe mode's suppression is category-based, not "ignore all of `--settings`."** Its own help text
names what it disables — `CLAUDE.md, skills, plugins, hooks, MCP servers, custom commands and agents,
output styles…` — and env vars are not on that list. An isolated (safe-mode) run can still be handed
arbitrary environment variables through `--settings`, which is not a config-*loading* leak in the
sense this investigation cares about, but is a real residue: **`--settings` is not fully inert under
safe mode**, and a design that assumes "safe mode ignores `--settings` entirely" is wrong. Not tested:
`permissions`, `model`, or other `--settings` keys under safe mode — recorded as unmeasured, not
inferred from the two that were tested.

## 4. A leak `--setting-sources` cannot touch, found incidentally

Account-level MCP connectors (`claude.ai Gmail`, `Google Drive`, `Google Calendar`, `Pipedream`,
`Shen`, `Joi Hub` on this host) appear in `mcp_servers` under **every** `--setting-sources` value
tested — `project`, `user`, and `""` (empty/none) all show them. They are gated by `--safe-mode`
(absent under `--safe-mode --setting-sources project`) but not by `--setting-sources` at all. These
are not `.mcp.json`/`settings.json` entries — they are a separate, account-scoped registration layer
that `--setting-sources` was never going to reach, since that flag only governs which settings
*files* are read. Recorded as residue: a `sources=project` posture that believes it excludes "host
MCP" is wrong about this specific class of server.

Similarly, the host's auto-memory directory (`memory_paths.auto`, a K-specific feature, not a
`CLAUDE.md`) is still reported at `--setting-sources ""` — but the canary turn confirms its *content*
does not reach context at that posture (`USER_MEMORY=no`). So `memory_paths` showing a path is not by
itself evidence of a leak; consistent with the prior change's finding that `memory_paths` cannot
answer the `CLAUDE.md` question, extended here to auto-memory: the path field is metadata, not proof
of content.

## What was not measured

- `CLAUDE_CONFIG_DIR` combined with `--setting-sources` (the prior change already found
  `CLAUDE_CONFIG_DIR` alone fails auth for a reason distinct from and not fixable the way the empty-
  `$HOME` case was; combining it with `--setting-sources` was not re-tried here since it could not
  produce a completable turn to canary-test hooks/mcp against).
- `--settings` under safe mode for keys other than `env` and `hooks` (`permissions`, `model`,
  `mcpServers` if settable there).
- Whether `--setting-sources` gates `.claude/agents/` (subagent definitions) the same way it gates
  skills — not tested; inferred-but-unverified from the skill/mcp/hook/env parallel, stated here as
  an inference, not a measurement.
- Behavior on a repo nested inside another repo, or a worktree — this fixture was a flat single repo.

## Relationship to isolate-by-safe-mode

That change's posture (`--safe-mode --strict-mcp-config --disable-slash-commands`) is the answer to
"exclude everything." This exploration answers a different, additive question: a posture that admits
*only* workspace config exists and is real (`--setting-sources project,local`, no `--safe-mode`), and
is a strictly different mechanism from safe mode — not a variant of it, not composable with it. Cost:
approximately 20 `-p` turns against a tiny fixture, each near-zero (no large context, `--tools ""` or
a single `printenv`/`echo`) — comparable in shape to the prior change's ~$0.80, not separately totalled
here.
