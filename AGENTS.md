# Agent Instructions

## Operating model — how work happens here

Read this before touching anything. It states, as rules you can follow with no director present,
what the K project 160 fleet constitution requires plus what this repo's own OpenSpec config
already governs. `CLAUDE.md`'s "Where things go" table says what belongs here versus in K; this
section is the executable half of that split.

### Every change goes through OpenSpec

explore -> propose -> apply -> archive. No exceptions, including a documentation-only change —
this section was written as one (`write-down-the-operating-model`). Commands:
`.claude/commands/opsx/{explore,propose,apply,archive,update,sync}.md` (slash commands
`/opsx:explore`, `/opsx:propose`, `/opsx:apply`, `/opsx:archive`, ...), backed by the skills
`openspec-explore`, `openspec-propose`, `openspec-apply-change`, `openspec-archive-change`,
`openspec-update-change`, `openspec-sync-specs`. There is no ad-hoc edit path: a change that never
passes through `openspec/changes/` leaves nothing a successor — human or agent — can pick up if
the session dies mid-way.

**Explore does not authorize building.** `openspec/config.yaml`'s `context` block already states
this in full; read it there rather than here, so the rule has exactly one copy.

### Commit and push

- Commit with an explicit literal pathspec, never a staged index:
  `git commit -F <message-file> -- <literal paths>`. `git add <paths> && git commit` (no `--`)
  commits whatever else is sitting in the shared index, not just your paths.
- After any commit that adds new files, confirm `git diff --cached` is empty before moving on.
  Do not trust a `||` chained after a piped command to have caught a failure — it tests the last
  command in the pipe, not the commit.
- `PREK_ALLOW_NO_CONFIG=1` is expected on every commit in this repo.
- Full pathspec-discipline rationale, including the three prior forms of this rule that each
  failed while being obeyed: `orchestration.md` Article V.
- **Who may commit, and who may push, is not what the managed beads block below says** — see
  "Overrides to the managed block above" at the end of this file.

### Validating and archiving a change

- `openspec validate <change> --strict` must pass on the change itself before archiving.
  `openspec validate --specs --strict` on the promoted result is not a substitute — it is clean
  precisely when nothing was promoted. `orchestration.md` Article XIV.
- `openspec list` showing a change "Complete" means its tasks are complete, not that planning or
  archiving is. Check `openspec status --change <name> --json` — `isPlanningComplete`,
  `specs.existingOutputPaths` — before assuming a change is done.
- **Archiving is part of the change, not a step someone else does later.** A change that
  validates and is never archived leaves its result stale with every other check reading green.
  `orchestration.md` Article XV. If you cannot archive in the session that applied the change,
  say so explicitly — do not let the change read as finished.
- If the change made a non-obvious build-time choice, it owes an ADR before archiving —
  `openspec/config.yaml`'s `operations.archive.guidance` states the non-obvious test and the
  `Revisit trigger:` requirement; read it there rather than here.

### The end-to-end receipt

Every closing report answers: what would distinguish *built* from *works*? A green `make check`
proves the wiring compiles; it does not prove anything runs end to end. `orchestration.md`
Article XVI. If you cannot point at a receipt beyond the test suite, say that plainly instead of
letting a passing check imply more.

### One session, one working tree

This repo has one working tree; there is no per-session worktree or branch for concurrent
building. `orchestration.md` Article XVII's premise — one director/session holding a repository
at a time — is why. Evidence that something else is mid-change here is a blocker to report, not a
race to win.

### Where the rest of the constitution lives

`orchestration.md`, in K project 160 (`~/Documents/Knowledge/Projects/160-ai-factory/`, on a
machine that has it), is the fleet constitution in full — seventeen articles. The five cited above
are this repo's own statement, in this repo's own words, of the parts that are a worker's
mechanics *in this repo*. The rest — who dispatches, concurrency across multiple workers, the
reflection ritual, Denis-facing escalation — governs a fleet director, not a single session
working this repo, and is deliberately not restated here: a rule stated twice drifts, and K is
private while this repo is public, so the copy lives there and this file only cites it.

A run of this repo with no K clone reachable (a clone on another machine, CI) still has every rule
above in force. Only the drift check below degrades:

`tools/hooks/check_orchestration_citations.py`, run by `make check`, confirms every article id
cited above still exists (by id — a rename or renumbering is what it catches) in K's
`orchestration.md`, when that file is reachable on this machine, and skips cleanly — not fails —
when it is not. It does not verify the rule text above still matches K's prose; that is why each
rule here is written in this repo's own words rather than copied, and reviewed by a person, not a
generator.

## Issue tracking (beads)

This project uses **bd** (beads) for issue tracking. Run `bd prime` for full workflow context.

> **Architecture in one line:** Issues live in a local Dolt database
> (`.beads/dolt/`); cross-machine sync uses `bd dolt push/pull` (a
> git-compatible protocol), stored under `refs/dolt/data` on your git
> remote — separate from `refs/heads/*` where your code lives.
> `.beads/issues.jsonl` is a passive export, not the wire protocol.
>
> See [SYNC_CONCEPTS.md](https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md)
> for the one-screen overview and anti-patterns (don't treat JSONL as the
> source of truth; don't `bd import` during normal operation; don't
> reach for third-party Dolt hosting before trying the default).

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work atomically
bd close <id>         # Complete work
bd dolt push          # Push beads data to remote
```

## Non-Interactive Shell Commands

**ALWAYS use non-interactive flags** with file operations to avoid hanging on confirmation prompts.

Shell commands like `cp`, `mv`, and `rm` may be aliased to include `-i` (interactive) mode on some systems, causing the agent to hang indefinitely waiting for y/n input.

**Use these forms instead:**
```bash
# Force overwrite without prompting
cp -f source dest           # NOT: cp source dest
mv -f source dest           # NOT: mv source dest
rm -f file                  # NOT: rm file

# For recursive operations
rm -rf directory            # NOT: rm -r directory
cp -rf source dest          # NOT: cp -r source dest
```

**Other commands that may prompt:**
- `scp` - use `-o BatchMode=yes` for non-interactive
- `ssh` - use `-o BatchMode=yes` to fail instead of prompting
- `apt-get` - use `-y` flag
- `brew` - use `HOMEBREW_NO_AUTO_UPDATE=1` env var

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:970c3bf2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   bd dolt push
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

<!-- BEGIN BEADS CODEX SETUP: generated by bd setup codex -->
## Beads Issue Tracker

Use Beads (`bd`) for durable task tracking in repositories that include it. Use the `beads` skill at `.agents/skills/beads/SKILL.md` (project install) or `~/.agents/skills/beads/SKILL.md` (global install) for Beads workflow guidance, then use the `bd` CLI for issue operations.

### Quick Reference

```bash
bd ready                # Find available work
bd show <id>            # View issue details
bd update <id> --claim  # Claim work
bd close <id>           # Complete work
bd prime                # Refresh Beads context
```

### Rules

- Use `bd` for all task tracking; do not create markdown TODO lists.
- Run `bd prime` when Beads context is missing or stale. Codex 0.129.0+ can load Beads context automatically through native hooks; use `/hooks` to inspect or toggle them.
- Keep persistent project memory in Beads via `bd remember`; do not create ad hoc memory files.

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

### Override

`bd remember` is not this repo's memory system — the operator already runs a global,
cross-project one at `~/Documents/Knowledge/Agents/Claude/`. Use `bd` for durable
work-item tracking only. Session-scoped step tracking (Claude Code's `TaskCreate`) is a
different job than `bd`'s durable issues; use both, don't treat one as a substitute for
the other.
<!-- END BEADS CODEX SETUP -->

### Overrides to the managed block above

- **"Do not commit or push without clear authority from the active profile or the current user
  request" (managed block above) does not describe this repo's actual commit/push policy.**
  Commit authority for a worker session comes from having an active, applied OpenSpec change —
  see "Commit and push" earlier in this file. Push is a separate, narrower grant: K's D022 gives
  push authority to **the platform** — `runtime/turn.py`'s own `commit()`/`take_turn` machinery —
  not to a build/worker session. A session working this repo commits under Article V discipline
  and pushes only when the active dispatch says so explicitly; absent that, it does not push.
- The managed block's session-completion checklist (file issues for follow-up, run quality gates,
  update issue status) still applies as written; only the commit/push authority line is overridden.
- The "Override" note inside the BEADS CODEX SETUP block above names the operator's memory-system
  path directly. It sits inside a `bd setup codex`-managed region, so it is not edited here — an
  edit there would be silently reverted the next time that generator runs. Flagged, not fixed:
  a future re-run of `bd setup codex` regenerates that path verbatim into this public repo.
