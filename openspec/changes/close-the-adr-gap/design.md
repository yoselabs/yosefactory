Motivation: see [proposal.md](proposal.md).

## Context

Checked against disk before writing anything (Article XII):

- `decisions/README.md` is one line: "Build-time ADRs only. Design decisions live in P160
  (D015)." No pointer to it exists in `CLAUDE.md`, `AGENTS.md`, or any `openspec` skill/config —
  it is reachable only by already knowing to look in `decisions/`.
- `git log --oneline` since `0002` (2026-08-16) to today (2026-08-22): 190 commits;
  `openspec/changes/archive/` holds 20 entries in the same window. `decisions/` gained nothing.
- `.claude/skills/openspec-archive-change/SKILL.md` (and its `.opencode`/`.agents` mirrors) is a
  vendored, generic skill — identical across every repo on this machine that consumes `openspec`
  (confirmed: the same file exists verbatim under `~/Workspaces/{a2web,shelf,homelab,...}`).
  Editing it here would not be a repo decision, it would be a local fork of shared tooling that the
  next `openspec` upgrade silently discards. Not the seam.
- That skill's own step 1 **does** read a repo-local seam and treats it as considered input:
  `openspec instructions archive --change "<name>" --json`, whose `operationGuidance` field the
  skill is instructed to "read and consider every entry, and follow entries that are applicable."
  `openspec/config.yaml`'s `operations.archive.guidance` is exactly what populates that field
  (confirmed against the file's own commented example and `openspec instructions proposal`'s
  parallel `rules` mechanism, which is already live — `config.yaml`'s `rules.proposal` two bullets
  are visible in every `openspec instructions proposal --json` call this session made).
- `tasks.md` has no analogous per-repo hook point — task templates are generated per-change, not
  read from a shared config the way `operations.*.guidance` is.

## Goals / Non-Goals

**Goals:**
- Put the ADR obligation where a worker's own tooling already reads it at the exact moment a
  build-time decision is final and fresh: archive.
- Give every ADR a falsifiable revisit condition, named consistently with K's existing
  `revisit_trigger:` field so one audit sweep (`tools/audit.py triggers`, per the director's
  correction) covers both stores.
- Backfill the decisions this repo already made and only documented in code.

**Non-Goals:**
- A mechanical archive-time check that blocks on a missing ADR. "Non-obvious" needs judgment; a
  hard gate either misses judgment calls or blocks trivial ones. Left as advisory guidance, same
  as `rules.proposal`'s two existing bullets, which are also unenforced and effective anyway
  (visible in every proposal this repo's workers have written since `config.yaml` existed).
- Editing the vendored `openspec-archive-change` skill itself, anywhere it appears on this
  machine.
- A second copy of the ADR rule in `CLAUDE.md`/`AGENTS.md`/`build-loop.md`. Exactly the failure
  mode named four times now (signal S990).

## Decisions

### D1 — the hook is `openspec/config.yaml`'s `operations.archive.guidance`, not the skill file or a task-template line

**Chosen:** a `operations: archive: guidance:` list in `openspec/config.yaml`, read by every
archive operation in this repo via the CLI's own `openspec instructions archive` lookup — no new
tooling, reusing a mechanism (`operationGuidance`) the installed `openspec` (1.8.0) already ships
and the archive skill already honours.

**Over, considered and rejected:**
- **Edit the vendored skill file.** Rejected in Context above — shared across every repo on this
  machine, silently reverted by the next `openspec` sync.
- **A checklist line in each change's `tasks.md` template.** Rejected — `tasks.md` is generated
  per-change from the schema template, not read from a repo-local config; adding the line would
  mean editing every future change's tasks by hand or forking the schema, and a per-change
  checklist item is exactly as skippable as the README already was (it decays the same way,
  one level closer).
- **A hard validation check (`openspec validate` failing without an ADR).** Rejected in
  Non-Goals — "non-obvious" is not mechanically decidable, and a false-positive gate on a trivial
  change teaches workers to route around it, the same lesson `orchestration.md`'s own "what is not
  yet mechanical" table already states about Article XII and the dispatch template.

### D2 — the header line is `Revisit trigger:`, not `Overturned if:`

**Chosen:** `Revisit trigger:` in the ADR header block (Status/Date/Supersedes/**Revisit
trigger**), matching K's existing `revisit_trigger:` field name on mechanisms exactly. The
director corrected the original dispatch (which named `Overturned if:`) mid-task: `tools/audit.py
triggers` was just extended to sweep decisions using the same field name, and a synonym here would
split one review discipline into two half-read ones — the same shape of failure this whole change
exists to close one level up.

**The bar stays the same either name:** a falsifiable, dated observation ("if X is measured/
observed, revisit"), not "if requirements change." Demonstrated per-ADR below.

## Risks / Trade-offs

- **Advisory guidance is still skippable** — a worker archiving fast can ignore
  `operationGuidance` same as it could already ignore `rules.proposal`. Accepted: the alternative
  (a hard gate) trades a missed ADR for a false-positive block, which is a worse failure to debug
  under Article II (never blocks in silence, but a spurious block still costs a report-and-wait
  round trip for something that was never actually a decision).
- **Six ADRs backfilled from commit messages and archived-change docs, not from a live memory of
  writing them.** Mitigated by grounding every claim in a specific commit SHA, git log, or archived
  change's own `design.md`/`tasks.md` — quoted, not reconstructed from the docstring alone. Where a
  docstring's claim and the code's actual behaviour disagreed, that is reported to the director
  separately (none found this session).

## Migration

None. Additive: one config block, one template line, six new files. No existing ADR is edited;
0001/0002 are untouched.
