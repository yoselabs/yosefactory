# Exploration — what actually isolates an agent run

Measured 2026-08-16 against `claude 2.1.225` on macOS, subscription auth, no `ANTHROPIC_API_KEY` and
no `CLAUDE_CODE_OAUTH_TOKEN` in the environment. Total cost of the investigation ~$0.80.

## Two instruments, and needing two is the first finding

1. **init probe** — `claude -p hi --output-format stream-json --verbose <flags>`, read stdout until
   the `system|init` event, then SIGTERM. Cheap: the configuration set is announced before the model
   answers, so the probe costs almost nothing.
2. **canary turn** — a real `-p` turn with `--tools ""`, asking whether a token is present in
   context. Tools are disabled so the answer cannot come from the agent reading a file.

The second is not a refinement. **`memory_paths` never lists a repository `CLAUDE.md` in any
posture**, so the init event cannot answer the `CLAUDE.md` question at all. And init is emitted by
runs that then fail to authenticate, so an init-only verdict certifies postures that cannot run.

Fixture — a scratch git repository, hostile on purpose:

```
CLAUDE.md                              token REPO_CANARY_MEMORY
.claude/settings.json                  {"env": {"REPO_CANARY_ENV": "loaded"}}
.claude/skills/repo-canary/SKILL.md
.claude/agents/repo-canary-agent.md
.mcp.json                              server "repo-canary-mcp"
```

User-level canary: the token `global-claude.md`, present in the host's own user instruction file.

## The table

Counts are from `system|init`. `repo s/a/m` is whether the repository's canary skill, agent and tool
server appear there. The two rightmost content columns are canary turns, not init.

```
   posture                                        memory      sk  pl  mcp  repo s/a/m   repoMD   userMD   auth
A  (none — baseline)                              host-auto   41   2    9   yes yes yes  PRESENT  PRESENT  ok
B  --strict-mcp-config --permission-mode manual   host-auto   41   2    0   yes yes  no    —        —      ok
C  --safe-mode                                    none        18   1    0    no  no  no  ABSENT   ABSENT   ok
D  --setting-sources ""                           host-auto   19   0    6    no  no  no  ABSENT   ABSENT   ok
E  HOME=<empty dir>                               fresh       16   0    1   yes yes yes  PRESENT  ABSENT   not logged in
F  CLAUDE_CONFIG_DIR=<scratch>                    fresh       16   0    1   yes yes yes    —        —      not logged in
G  F + --setting-sources "" --strict-mcp-config   fresh       15   0    0    no  no  no    —        —      not logged in
H  --safe-mode + F                                none        15   0    0    no  no  no    —        —      not logged in
I  --safe-mode --strict-mcp-config                none        18   1    0    no  no  no  ABSENT   ABSENT   ok
K  I + --disable-slash-commands                   none         0   1    0    no  no  no  ABSENT   ABSENT   ok
```

**B is what shipped.** It isolates nothing: the host's memory, the host's skills and the
repository's own skill and agent all load under it.

## 1. The emptied home does not work, and never did what it was credited with

E, F, G and H all fail identically: `Not logged in · Please run /login`, `total_cost_usd: 0`, no turn.

The failure is **auth-only, and narrower than that — keychain-location-only**. There is no
`~/.claude/.credentials.json` on this host; the subscription credential is in the macOS login
keychain, which lives *under* `$HOME`. A fresh home moves the store out from under the process, so
the credential is not missing, it is unfindable.

Discriminating run — an empty home containing exactly one entry, `Library` symlinked to the real one:

```
HOME=<empty dir with Library -> ~/Library>   →   repo CLAUDE.md PRESENT, user CLAUDE.md ABSENT, $0.047, ran fine
```

Nothing else about the binary breaks. And that run is also the honest statement of what an emptied
home ever controlled: **one of three surfaces.** It hides the user's configuration and leaves the
repository's entirely intact.

`CLAUDE_CONFIG_DIR` fails for a different reason — the keychain is still reachable, the account state
is not — which matters because the keychain case is fixable by a symlink and this one is not.

## 2. `--safe-mode` is the mechanism

Its own help text: *"Start with all customizations (CLAUDE.md, skills, plugins, hooks, MCP servers,
custom commands and agents, output styles…) disabled… Auth, model selection, built-in tools, and
permissions work normally."* Measured true, including the auth clause — it is the only candidate that
suppresses both `CLAUDE.md` layers and still runs.

Against the three surfaces separately:

| surface | control | residue |
|---|---|---|
| user config in `$HOME` | `--safe-mode` | one host-installed plugin still registers |
| repository config | `--safe-mode` **or** `--setting-sources ""` | none |
| global skills and plugins | `--safe-mode --disable-slash-commands` | the plugin stays listed, contributing 0 skills and 0 commands |

`--setting-sources ""` is a genuine second control, strictly weaker — it leaves 6 host tool servers
and the host auto-memory directory — but surgical, and it does **not** disable hooks. Kept in the
record rather than discarded, because a run that wants a repository's own conventions but not the
host's is a real posture.

## 3. Safe mode is a floor, not a base to build on

Explicit re-admission of a tool server does not survive it:

```
--safe-mode --strict-mcp-config --disable-slash-commands --mcp-config <explicit>   →  mcp = 0
--safe-mode --mcp-config <explicit>                                                →  mcp = 0
--strict-mcp-config --mcp-config <explicit>            (no safe mode)              →  mcp = 1
```

So the toggle is binary rather than compositional: an isolated run cannot be handed a tool server.
This change refuses that combination in the policy instead of emitting a flag that does nothing —
silently ignoring an argument is the exact failure the whole investigation is about.

Not measured: whether `--settings` survives safe mode. Stated rather than assumed.

## 4. Configuration isolation is not filesystem isolation

Under posture K, asked to, the agent read the host's user instruction file with the Read tool and
reported success. No flag in the surface bounds where an agent may read. That is a different threat
with a different control — a filesystem boundary — and it is recorded as named residue rather than
chased with flags.

## 5. Two side observations, recorded and not acted on here

- **`permissionMode` in the init event is not the flag.** `--permission-mode manual` reports
  `default`; passing nothing reports `auto`. The field cannot verify the permission posture, so
  nothing asserts on it.
- **`--max-budget-usd` exists at this version**, and `EMULATED` declared a cost ceiling absent. The
  false claim is corrected here because §7b rule 4 forbids an unchecked capability claim; wiring the
  flag is a separate change.
