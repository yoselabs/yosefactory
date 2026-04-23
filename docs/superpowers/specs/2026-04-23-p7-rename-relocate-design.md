---
title: "P7 — Rename & relocate (minimum vision alignment)"
type: spec
status: Executed
owner: "@iorlas"
created: 2026-04-23
updated: 2026-04-23
rfc: "../../rfcs/0001-v1-scope.md"
author:
  human: "@iorlas"
  agent: "claude-opus-4-7 (V1.0 execution session 2026-04-23)"
---

# P7 — Rename & relocate

## Goal

Move the packages P5/P6 introduced as nested subpackages into their
vision §7.1 top-level positions so P8's import-linter contract can
match the boundaries verbatim. No behavior change; pure relocation
with import fixups.

The phase deliberately targets **boundary alignment, not full name
alignment** with vision §7.1. `lifecycle/` does not rename to
`session/`; `pipeline/` does not collapse to `pipeline.py`; `agent/`
package construction is skipped. These names are cosmetic — P8
enforces the *boundaries*, not the vocabulary, and the vision doc
remains the canonical vocabulary source. Post-V1.0 cleanup can revisit.

V1.0 success criterion: `ingress/`, `gating/`, `middleware/`,
`effects/`, `composition/`, `observability/` exist as top-level
packages with the same contents P5/P6 gave their nested versions.

Seventh V1.0 migration-phase spec. Appetite: **2 days.**

## Non-goals

- **No `lifecycle/` → `session/` rename.** Vision §7.1's session/
  vocabulary stays canonical in the doc; P8 contracts reference
  `lifecycle/` verbatim.
- **No `pipeline/` → `pipeline.py` collapse.** `pipeline/` stays as
  a slim package housing `dispatch.py`, `runner.py`,
  `stage_executor.py`.
- **No `agent/` package construction.** `assembly/prompt.py` stays in
  place; runner + stage_executor stay in `pipeline/`.
- **No `config.py` → `config/` package.**
- **No signature changes, no behavior changes.** Pure relocate.
- **No subscriber moves.** `adapters/subscriber/` stays — subscribers
  are adapters (they adapt the progress bus to external outputs).
  Vision §7.1 mentions them in both `adapters/` and `observability/`;
  resolving to `adapters/subscriber/` preserves the adapter-boundary
  story.

## Plan

Each step = one commit. 9 steps. Each step must leave `make check`
green. Every step is `git mv` + sed-driven import fixups + a
run of `make fix && make check`.

Step order picked so earlier moves do not cascade-break later moves.
Step 1 first because `progress_format.py` has the most callers;
everything else depends on `observability/` existing.

1. **`domain/progress_format.py` → `observability/progress_format.py`.**
   New top-level `observability/` package. Create
   `observability/__init__.py`. `git mv` the 330-LOC file. Update
   every caller (grep `from a2sdlc.domain.progress_format`). Domain
   shrinks.

2. **`assembly/wire.py` → `observability/wire.py`.**
   Move + update callers (both CLI files). `assembly/` now holds
   only `prompt.py` + `composition.py`.

3. **`assembly/composition.py` → `composition/__init__.py`.**
   New top-level `composition/` package. Move + update callers
   (`cli/dispatch.py`, `cli/run_stage.py`, test file).
   `tests/assembly/test_composition.py` →
   `tests/composition/test_composition.py`.

4. **`pipeline/middleware/` → top-level `middleware/`.**
   `git mv` the whole subpackage. Update `pipeline/dispatch.py` +
   move `tests/pipeline/middleware/` → `tests/middleware/`.

5. **`pipeline/effects_apply.py` + `pipeline/stage_finish.py` →
   `effects/`.**
   New `effects/__init__.py` + `effects/apply.py` +
   `effects/stage_finish.py`. Update `pipeline/dispatch.py` (both
   imports) + internal imports within the new `effects/` package +
   move both test files to `tests/effects/`.

6. **`pipeline/ingress.py` + `pipeline/context.py` +
   `pipeline/feedback_routing.py` → `ingress/`.**
   `ingress.py` becomes `ingress/__init__.py`; `context.py` and
   `feedback_routing.py` become `ingress/context.py` +
   `ingress/feedback_routing.py`. Update callers
   (`pipeline/dispatch.py`, `tests/pipeline/test_ingress.py` →
   `tests/ingress/test_ingress.py`, `tests/fakes.py`).

7. **`pipeline/gating.py` + `pipeline/breakers.py` → `gating/`.**
   `gating.py` becomes `gating/__init__.py`; `breakers.py` becomes
   `gating/breakers.py`. Update callers (`ingress/__init__.py`,
   `middleware/idempotency.py`, `pipeline/dispatch.py`, tests).

8. **Update architecture docs.**
   `docs/architecture.md` §3 gains `ingress/`, `gating/`,
   `middleware/`, `effects/`, `composition/`, `observability/` in
   the layer rules. Repo `CLAUDE.md` reflects the slimmer `pipeline/`
   (only dispatch + runner + stage_executor).

9. **Spec status → Executed.**

## File-level changes

| From | To | Contents |
|---|---|---|
| `pipeline/ingress.py` | `ingress/__init__.py` | `parse_event`, `resolve_intent`, `resolve_routing`, `ParsedSkip` |
| `pipeline/context.py` | `ingress/context.py` | `assemble_context`, `pick_handover` |
| `pipeline/feedback_routing.py` | `ingress/feedback_routing.py` | `resolve_target_stage` |
| `pipeline/gating.py` | `gating/__init__.py` | `check`, `check_ticket_active`, `check_duplicate_run_id` + re-exports |
| `pipeline/breakers.py` | `gating/breakers.py` | `check_review_cycles`, `check_cost_ceiling` |
| `pipeline/middleware/` | `middleware/` | `StageAttempt` / `Middleware` aliases, `with_idempotency`, `with_telemetry` |
| `pipeline/effects_apply.py` | `effects/apply.py` | interpreter |
| `pipeline/stage_finish.py` | `effects/stage_finish.py` | `outcome_to_dispatch_result`, `pipeline_pause_reason` |
| `assembly/composition.py` | `composition/__init__.py` | `CompositionProfile`, resolver, validator, builders |
| `assembly/wire.py` | `observability/wire.py` | `build_progress_state` |
| `domain/progress_format.py` | `observability/progress_format.py` | `format_final`, `format_error`, `context_window_for_model`, 330 LOC |

## Test directory moves

| From | To |
|---|---|
| `tests/pipeline/middleware/` | `tests/middleware/` |
| `tests/assembly/test_composition.py` | `tests/composition/test_composition.py` |
| `tests/pipeline/test_ingress.py` | `tests/ingress/test_ingress.py` |
| `tests/pipeline/test_gating.py` | `tests/gating/test_gating.py` |
| `tests/pipeline/test_breakers.py` | `tests/gating/test_breakers.py` |
| `tests/pipeline/test_effects_apply.py` | `tests/effects/test_apply.py` |
| `tests/pipeline/test_stage_finish.py` | `tests/effects/test_stage_finish.py` |

Tests for `pipeline/dispatch.py`, `pipeline/runner.py`,
`pipeline/stage_executor.py` stay under `tests/pipeline/` (their
source files stay in `pipeline/`). `tests/pipeline/test_context.py`
(if present) moves to `tests/ingress/test_context.py` alongside the
moved `pipeline/context.py` → `ingress/context.py`.

## Test strategy

- **Pure import-path changes.** No assertion edits.
- **`make check` after every step.** Diff-coverage must stay at 100%
  for every commit — each moved file ships with its moved tests.
- **Cassette tier** — untouched. Adapter paths don't move.
- **Import-linter** — if the existing contract file references
  package paths, update in the same commit as the move. Harness
  enforces at `make check`.

## Security considerations

- **No external surface change.** All relocations are internal.
- **No credential path change.** The factory + subscriber paths that
  handle tokens (`adapters/factory.py`, `adapters/subscriber/`) are
  untouched.

## Rollout

Ships on main one step at a time. Each step is a single atomic `git
mv` + import fixup commit. Highest-risk step is **step 6** (ingress
package) because the most callers touch `resolve_intent` /
`parse_event` — any missed import breaks dispatch. Mitigation: grep
before committing; `make check` after committing.

Step 8 (docs) is pure docs; no code risk. Step 9 is status flip.

Not feature-flagged. Relocations don't benefit from runtime toggles.

## Backout

Each step is a single atomic commit. Revert is `git revert <sha>`.
Steps are independent — reverting one leaves the tree in a
consistent prior state because each move is unidirectional and the
sed-driven import updates are one-to-one.

## Links

- RFC: [../../rfcs/0001-v1-scope.md](../../rfcs/0001-v1-scope.md)
- Architecture vision §7.1 (target package layout — the P7 target)
- Architecture vision §10 ("1 day rename + relocate")
- P6 spec (prerequisite): `2026-04-23-p6-unified-composition-design.md`
- P8 spec (sequel): import-linter lockdown against this layout
