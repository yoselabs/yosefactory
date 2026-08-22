# ADR-0004 — `turn.commit()` is the sole function that composes platform trailers

**Status:** Accepted
**Date:** 2026-08-16
**Supersedes:** —
**Superseded by:** —
**Revisit trigger:** a second code path is found (or proposed) that writes a git commit on the
platform's behalf without going through `runtime/turn.py::commit()` — including the workspace
delivery path added by ADR-0005, which reuses this function's trailer composition rather than
duplicating it.

## Context

D014 (P160) measures one thing: a commit to `a2web` produced through the platform. Before
`mark-platform-authored-commits` (archived 2026-08-16), nothing in a commit distinguished a
platform turn from a hand-driven Claude Code session — both emitted the same harness
`Co-Authored-By: Claude <model>` trailer, so the measurement's own unit could not be read off its
artefact.

Denis authorised the mechanism directly (`orchestration.md`, 2026-08-16): *"fine to leave what
harness provides. but later on we will add yosefactory as another co-author."*

## Decision

`runtime/turn.py::commit()` is the only function in this codebase that composes the platform's
trailers, via `git interpret-trailers`, appending two:

- `Co-Authored-By: yosefactory <yosefactory@yoselabs.dev>` — the authorship claim.
- `Yosefactory-Run: <run_id>` — the route from the commit back to its ledger record.

Trailers are appended by deterministic code at the commit call, never composed by the agent and
never mentioned in a skill file — a convention that depends on a model habitually typing a line
into a `-m` message is not a mechanism (`orchestration.md`'s own "Commit attribution" section
names exactly this failure for the harness's `Co-Authored-By: Claude` line, which stopped
appearing the day Article V forced everyone off `-m`). Composition has **no fallback**: if
`git interpret-trailers` fails, the commit is refused rather than landing untagged.

Two trailers, never folded into one: git keys the co-author identity on the `Co-Authored-By` line
alone, so embedding a run id inside it would register every run as a different author.

## Consequences

- Every platform-authored commit — queue and (per ADR-0005) workspace — carries both trailers or
  does not exist; there is no code path that produces a platform commit silently missing them.
- Past commits made before 2026-08-16 are not retrofitted (D002 — nothing is ever deleted, no
  rewriting); the inconsistency is resolved forward only.
- A future second commit path (a new workflow, a new place) must call this same function rather
  than reimplement trailer composition, or D014's measurement unit fragments again the way it did
  before this ADR's decision — this is exactly the gap ADR-0005 closed for the workspace commit.

## References

- `src/yosefactory/runtime/turn.py::commit()`, `_with_platform_trailers`.
- `openspec/changes/archive/2026-08-16-mark-platform-authored-commits/proposal.md`.
- `openspec/specs/commit-attribution/spec.md`.
- P160 D014, H565.
