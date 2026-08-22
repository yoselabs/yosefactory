## Why

Promotion: **K project 160, D024** (2026-08-22) — the factory moves into CI, and CI removes the
director. Every rule a worker here follows today — OpenSpec is mandatory, explore before propose,
archive it yourself, who may push — holds because a director typed it into that morning's dispatch,
not because this repo states it. Measured: `grep -ci openspec CLAUDE.md AGENTS.md` → 0, 0;
`grep -c "Article [IVX]" both` → 0, 0. `AGENTS.md` is 136 lines of beads/shell-hygiene vendor
boilerplate — useful, but not an operating model. The actual constitution
(`~/Documents/Knowledge/Projects/160-ai-factory/orchestration.md`, seventeen articles) lives only
in K, a different, private repo. An operating model carried in the operator's prompts does not
survive the thing D024 is building. This is the fifth measured instance of K's S990 (an instruction
decays with distance from the action), and by some distance the largest.

No build-time code decision is at stake here in the usual sense — this is `AGENTS.md`/`CLAUDE.md`
authorship, a decision about *how this repo records how it works*, which per `CLAUDE.md`'s own
table ("a decision about how it got built -> `decisions/` here") is squarely this repo's business,
same framing `close-the-adr-gap` used for the same class of direct dispatch.

## What Changes

- **`AGENTS.md` becomes the worker-facing operating model.** States, as rules a worker follows
  with no director present: every change goes through OpenSpec (explore -> propose -> apply ->
  archive, no exceptions including docs-only), naming the actual commands/skills in this repo
  (`.claude/commands/opsx/`, `.claude/skills/openspec-*`); that explore does not authorize
  building (pointing at `openspec/config.yaml`'s `context` block, not restating it); the commit/push
  rules actually in force; where an ADR is owed (pointing at `openspec/config.yaml`'s
  `operations.archive.guidance`). The beads/shell-hygiene material stays, demoted below the
  operating model rather than removed.
- **A handful of this repo's fleet-worker *mechanics* — commit pathspec discipline, the archive
  step, one director per repo — stated natively in `AGENTS.md`, each citing its K `orchestration.md`
  article id, in this repo's own words. Fleet/design governance (dispatch shape, concurrency rules,
  reflection ritual, the eleven articles that govern the director rather than a worker's mechanics
  in this repo) is explicitly NOT restated.**
- **A drift checker, not a generator**: `tools/hooks/check_orchestration_citations.py` greps
  `AGENTS.md` for cited article ids and confirms each still exists (by id, not renumbered away) in
  K's `orchestration.md`, when that file is reachable on this machine. Skips cleanly, does not
  fail, when K is absent (a clone on another machine, or CI). Wired into `make check` — not the
  pre-commit hook — because K is routinely absent for other clones/CI and a pre-commit hook that
  silently no-ops most of the time is exactly the false-confidence shape `orchestration.md` Article
  XII warns against; `make check` is a rarer, more deliberate invocation where a developer expects
  to see what actually got skipped.
- **Model contradiction (`CLAUDE.md` Stack vs `decisions/0006`) resolved.** Verdict: genuine
  contradiction, not ambiguity — both name the same subject (the model `claude-agent-sdk` invokes
  as this platform's harness/executor), `CLAUDE.md`'s line predates ADR-0006 by eight days and was
  never updated when the ADR superseded it. The standing ruling wins. `CLAUDE.md` now points at
  `decisions/0006-executor-pinned-to-sonnet-5-medium.md` instead of restating a value that drifts.
  A new ADR (`decisions/0009`) records the contradiction and its resolution, because a future
  worker editing `CLAUDE.md`'s Stack section could plausibly restore the stale value without
  knowing ADR-0006 exists.
- **Beads commit/push profile reconciled.** The managed block's "do not commit or push without
  clear authority" is real guidance for an unbriefed session but is routinely and correctly
  overridden by dispatch (K D022 grants the platform push; `orchestration.md` Article V governs
  worker commits directly). States the actual rule in force under `CLAUDE.md`'s existing
  "Overrides to the managed block above" section — survives the managed block being regenerated.
- **Host-path triage (`AGENTS.md`, `CLAUDE.md`, `decisions/0001`).** Every tilde-shorthand
  occurrence enumerated and classified functional / gratuitous / over-disclosing. Only the
  gratuitous/over-disclosing ones are fixed (two occurrences: `AGENTS.md`'s beads override,
  `decisions/0001`'s reference to the operator's personal memory-system path — both replaced with
  prose, no path). `CLAUDE.md`'s own paths are covered by an existing disclaimer whose wording is
  broadened by one line so it plainly covers the whole file, not just the block directly under it.
  The shelf resolver block and functional command examples are untouched.

## Non-goals

- No generator mirroring K's `orchestration.md` into this public repo (explicitly rejected by the
  dispatch — a private-to-public copy machine, and this program already paid for that leak once).
- No restating fleet/dispatch/concurrency governance that has no bearing on a worker's mechanics
  in this repo.
- No bulk rewrite of every tilde path in the repo.
- No runtime code changes (`src/`) — (c) is resolved as a documentation correction; no code
  currently reads `CLAUDE.md`'s Stack section, only `decisions/0006`'s constants govern behavior.

## Grounded in

`~/Documents/Knowledge/Projects/160-ai-factory/orchestration.md` (Articles cited individually in
`AGENTS.md`), `~/Documents/Knowledge/Projects/160-ai-factory/build-loop.md`,
`openspec/config.yaml`, `decisions/0006-executor-pinned-to-sonnet-5-medium.md`,
`openspec/changes/archive/2026-08-22-close-the-adr-gap/` (precedent for this class of
direct-dispatch documentation change).
