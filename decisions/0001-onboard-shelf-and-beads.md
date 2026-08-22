# ADR-0001 — Onboard as a shelf consumer, adopt beads

**Status:** Accepted
**Date:** 2026-08-13
**Supersedes:** —
**Superseded by:** —

## Context

D001 (P160) already commits this repo to consuming the shelf; the handover's §2 table lists
`~/Workspaces/shelf`'s onboarding runbooks as prior art to read before building anything similar.
`~/Workspaces/shelf/docs/runbooks/onboard-a-consumer.md` (Phase A: commit guard, resolver block,
beads, linter preset) and `adopt-beads.md` are the mechanism; this ADR is the record of applying
them here, and the calls that runbook explicitly leaves to the consumer rather than defaulting.

Explored first via `/opsx:explore` before acting (session transcript, 2026-08-12): grounded in the
actual repo state — `core.hooksPath` unset, `.git/hooks/pre-commit` already held prek's shim,
`.pre-commit-config.yaml` already existed — before deciding whether onboarding was safe.

## Decision

**Onboard Phase A now; defer Phase B–F (the substrate-inventory sweep) until there's a real
hand-rolled codebase to audit.** Phase A is mechanical and reversible; the sweep needs volume this
repo doesn't have yet (9 tracked files at the time of onboarding).

**Guard: wired through `.pre-commit-config.yaml`, not shelf's native-hook path.** The
`onboard-consumer` skill's `guard` operation refuses to clobber a foreign `.git/hooks/pre-commit`
(prek's shim was already there) and reports `failed` — correctly, per its own non-clobber
discipline. Its own error message names the pre-commit-framework route as the alternative:
a `shelf-guard` entry in `.pre-commit-config.yaml` calling `make guard`. Verified live —
`prek run shelf-guard --all-files` — rather than trusting the automated tool's own (necessarily
narrower) verification, which can't see this path.

**Beads: embedded mode, no server mode.** The shelf's default is opt-out, not opt-in — most shelf
consumers use it, and `bd`'s ordering guarantees (`beads` operation refuses to run before `guard`
verifies) protect against the runbook's worst documented hazard, `bd init` seizing
`core.hooksPath` with no native hook to chain into. That precondition already held here. Server
mode was not adopted speculatively — embedded is correct until concurrent-write conflicts are an
observed problem, matching the runbook's own stated default and this program's N=1 constraint
(philosophy.md, no second-user design target).

**`bd init` did switch `core.hooksPath` to `.beads/hooks`** despite reporting "Preserving existing
pre-commit hook" — that message is about hook *content*, not about which mode git ends up in. This
is exactly the mode-switch hazard `adopt-beads.md` §2.1 documents on other repos, now confirmed
here too. Not a defect: the switch preserved prek's shim body verbatim and chained bd's own block
before it, so execution still reaches `prek hook-impl` at the end. Verified end-to-end with
`sh .beads/hooks/pre-commit` (ruff, ty, shelf-guard all fired) before trusting a real commit to it.

**`bd dolt push` does not ride along with a plain `git push`** — confirmed, not assumed: the
runbook's §2.2 gap is real on this repo too. Chained it onto `.beads/hooks/pre-push`, outside bd's
managed markers, non-fatal on failure. Verified with a direct hook run before a real push, then
confirmed again on the real push.

**`bd remember`/`bd prime`: declined for persistent agent memory.** `bd init`'s injected
`CLAUDE.md`/`AGENTS.md` block defaults to this; the operator already runs a global, cross-project
memory system, outside this repo, that predates this repo and isn't repo-scoped. Stated explicitly
in both files, right after bd's managed block, per `adopt-beads.md`
§1.6's own instruction not to let this default in silently. `TaskCreate`/`TaskUpdate` (session-scoped
step tracking) stays in use alongside `bd` (repo-durable issues) — different scope, not a
duplicate.

**The linter preset is a one-shot scaffold, pruned on landing, not left as copied.** Its own
docstring says so: "copy, then the consumer owns it." Shelf's own `pyproject.toml`/`Makefile`
tables came in with shelf-package-specific test deps (`convert-md`, `anyllm`, `zendriver`,
`browser-cookie3`, `python-docx`, `hypothesis`) and a `packages/*/` monorepo layout that doesn't
match this repo's single `src/yosefactory/`. Dropped the deps this repo has no consumer for yet;
rewrote the `packages/*/`-shaped Makefile targets (`spell`, `deps`) and `[tool.coverage.run]`
source to the real layout. Re-running the onboarding script re-added the shelf-shaped versions
once — the operation only appends names it finds absent, so removing a copied target makes it
look "genuinely absent" on the next run. Pruned it back out both times; this is expected friction
from the tool's own documented idempotency contract, not a bug.

## Consequences

**Positive**

- Commit guard is live and ready for the day a shelf package is actually adopted (DEEP·STABLE·WINS,
  a separate decision each time, never a side effect of onboarding).
- `bd` gives Session 1's already-real need — traceable work items in `a2web` (`a2web-uh6`) — a home,
  and gives this repo the same for its own build-time backlog going forward.
- Both real hazards the runbook documents from other repos (`core.hooksPath` seizure, the Dolt
  push gap) were hit here too and fixed the same way, rather than assumed not to apply.

**Negative / accepted cost**

- Two memory-adjacent instructions (`bd remember`, "don't use TaskCreate") now live in
  `CLAUDE.md`/`AGENTS.md` as bd's default text plus this repo's override immediately after —
  slightly more to read per session than a repo with no override, in exchange for not silently
  losing the existing memory system.
- The linter preset needs re-pruning if `onboard-consumer`'s script is ever re-run before this
  repo grows a `packages/*/`-shaped layout (it won't) or genuinely adopts the deps it dropped.

**Rejected alternatives**

- **Hand-edit `.git/hooks/pre-commit` (prek's generated shim) to add the guard's native-hook
  line.** Rejected: the file is prek-owned and regenerated; hand-editing a generated file is advice
  that breaks on the owner's next regeneration, the same reasoning the shelf installer itself gives
  for not editing `husky`/`lefthook`-owned files.
- **Server-mode beads, or a remote-sync chain built ahead of a second writer.** Rejected as
  speculative — no concurrent-write conflict has ever been observed, and this program has no
  second-user design target (philosophy.md, S041).
- **Leave `bd remember`/"don't use TaskCreate" as bd's default.** Rejected: silently losing the
  existing global memory system, or losing session-scoped step tracking, are real regressions
  the runbook's own §1.6 flags as a decision, not a default.

## References

- `~/Workspaces/shelf/docs/runbooks/onboard-a-consumer.md`
- `~/Workspaces/shelf/docs/runbooks/adopt-beads.md`
- `~/Workspaces/shelf/.agents/skills/onboard-consumer/SKILL.md`
- P160 D001 (the shelf is part of the factory), D015 (build/design boundary)
- Commits: `ebd0de5` (bd init), `6856d6a` (shelf+beads onboarding),
  `2c99b04` (dolt-push chain fix)
