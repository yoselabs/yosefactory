---
title: "P4 — Pipe-and-filter dispatch"
type: spec
status: Executed
owner: "@iorlas"
created: 2026-04-25
updated: 2026-04-23
rfc: "../../rfcs/0001-v1-scope.md"
pitch: "../../pitches/2026-04-23-v1-scope.md"
author:
  human: "@iorlas"
  agent: "claude-opus-4-7 (V1.0 execution session 2026-04-25)"
---

# P4 — Pipe-and-filter dispatch

## Goal

Collapse `pipeline/dispatch.py` to the composition-root shape from
architecture vision §7.3 — **≤ 80 LOC**, no logic beyond wiring. Extract
the two bounded contexts currently buried in `preflight.py` into their
own modules: **ingress** (event parse + intent resolution) and **gating**
(pre-stage checks — ticket active, idempotency, circuit breakers).
Narrow the fat `DispatchContext` into a `RunContext` that carries only
what handlers + interpreter need. Rename `PreflightOutcome` to
`RunIntent` to reflect its role: "what the pipeline intends to do for
this run."

This is the payoff phase — the whole P1→P3 rearrangement existed so
P4 could cleanly split one 240-LOC orchestrator across three named
packages, each testable in isolation. V1.0 success criterion: the
composition root reads like the pseudocode in vision §7.3.

**P4 does NOT introduce middleware (P5), CompositionProfile (P6), or
final package renames (P7).** Those stay for their own phases.

Fourth V1.0 migration-phase spec. Appetite: **1.5–2 weeks.**

## Non-goals

- **No middleware onion.** `idempotency` check stays in `gating/`
  rather than a middleware wrapper — P5 extracts it.
- **No `CompositionProfile`.** The CLI still threads adapters into
  `RunContext` by hand. P6 introduces the profile type.
- **No module renames beyond the ones this phase introduces** —
  `pipeline/` stays as the location for ingress/gating/dispatch until
  P7 relocates them to the vision's §7.1 tree.
- **No full Event ADT migration.** `WorkAdapter.parse_event` still
  returns `PipelineEvent` in V1.0; `ingress/` exposes the structural
  classification (skip / closed / label / feedback / proceed) as
  pattern-matchable shapes over `PipelineEvent`. Full ADT retrofit is
  post-V1.0 (RFC-0001 §Data model decision).
- **No changes to StageHandler Protocol signature.** Handlers still
  take `ctx` with pre-populated per-run fields. Per-vision the target
  is `execute(ctx, intent)` but threading the second argument through
  four handlers + the interpreter is a P7/P8 concern. P4 keeps
  `execute(ctx)`; `intent` lives *on* ctx as `ctx.intent`.
- **No `preconditions()` adoption.** All handlers still return `None`.
  Preflight-equivalent gating stays centralized in `gating/`. Per-stage
  precondition migration waits for a later clean-up pass.

## Plan

Each step = one commit. 10 steps grouped into 4 stages. Each step must
leave `make check` green.

### A. Extract bounded contexts (additive, preflight stays)

1. **`pipeline/ingress.py` — event parse entry.**
   New module. Exposes ``parse_event(ctx) -> PipelineEvent`` (thin
   wrapper over ``ctx.work.parse_event()`` with the ``SkipEvent``
   exception → skip-short-circuit semantics). Caller pattern-matches
   the returned event's fields (``is_closed``, ``pr_number``,
   ``trigger_stage``) to decide flow.
   *L1 tests:* parse happy-path; parse SkipEvent → ``None`` sentinel;
   parse on closed ticket returns event with ``is_closed=True``.

2. **`pipeline/ingress.py` — intent resolution.**
   Add ``resolve_intent(ctx, event) -> RunIntent`` that owns the
   routing logic currently in ``preflight._resolve_routing``. Emits a
   ``RunIntent`` (new dataclass — a rename of ``PreflightOutcome`` with
   the same fields but different name and location).
   *L2 test:* `resolve_intent` against label / feedback / proceed /
   closed-feedback-already-addressed paths — matches existing preflight
   behavior end-to-end via a parameterized fixture.

3. **`pipeline/gating.py` — pre-stage checks.**
   New module. Exposes ``check(ctx, event) -> BlockReason | None`` that
   runs the per-event gate sequence:
   - ticket-active check (skip if closed-ish)
   - idempotency check (duplicate run_id)
   - circuit breakers (review-cycles, cost ceiling)
   Returns the first blocking reason or ``None`` to proceed. Replaces
   the scattered ``run_preflight`` checks.
   *L1 tests:* per-rule — one test each for each check's blocking /
   non-blocking conditions.

4. **`RunIntent` type.**
   Rename `PreflightOutcome` → `RunIntent`, move to
   `domain/run_intent.py`. Fields unchanged (target_stage, base,
   branch, event, state, directives, gates, clean_body,
   user_prompt_override, self_answer, state_mgr). Pure data type, no
   I/O. Keep a `PreflightOutcome` alias pointing at `RunIntent` for
   one step to avoid breaking contract tests; drop it in step 9.
   *L1 tests:* round-trip + field access (minimal — it's a dataclass).

### B. Adopt the new surface in dispatch

5. **dispatch calls `ingress.parse_event` + `gating.check`.**
   `pipeline/dispatch.py::dispatch` replaces `run_preflight(ctx)` with:
   ```python
   event = ingress.parse_event(ctx)
   if event is None: return DispatchResult.skipped(...)
   if reason := gating.check(ctx, event): return DispatchResult.blocked(reason)
   intent = ingress.resolve_intent(ctx, event)
   ```
   `run_preflight` stays callable (same signature) but the dispatch
   path no longer uses it. Other callers (there are a few in tests +
   standalone-invocability) continue to use `run_preflight` — it's a
   thin composition of the new modules after step 5.

6. **`RunContext` dataclass — narrow context.**
   New `domain/run_context.py`. Shape:
   - `work`, `git`, `review`, `runner` — adapter handles
   - `progress_state`, `logger` — observability
   - `config`, `project_root`, `run_id`
   - `telemetry`, `make_comment_subscriber` — optional
   - `intent: RunIntent | None` — populated by dispatch after
     resolve_intent
   - `pre`/`pr_lifecycle`/`comment`/`pr_number`/`stage_config`/`run` —
     kept for handler compat (same transitional-fat pattern P2/P3
     used; P7 or a later pass tightens)
   `DispatchContext` becomes a type alias for `RunContext` in this
   step to avoid a big-bang rename of every test file. The alias
   dies in step 9.

7. **Handler per-run plumbing via `ctx.intent`.**
   Handlers today read `ctx.pre` to get the PreflightOutcome. Expose
   the same value via `ctx.intent` (both point at the same object,
   typed as `RunIntent`). Handlers keep reading `ctx.pre` in V1.0 —
   the rename + `ctx.intent` path is an alias-migration for readers
   that don't need the legacy name. One step; one commit; no behavior
   change.

### C. Collapse + cleanup

8. **Collapse `pipeline/dispatch.py` to the vision shape.**
   Target shape (≤ 80 LOC composition root):
   ```python
   async def dispatch(ctx: RunContext) -> DispatchResult:
       event = ingress.parse_event(ctx)
       if event is None:
           return DispatchResult(stage=StageName.SPEC, error="skipped")
       if event.is_closed:
           ctx.work.mark_done(event.key)
           return DispatchResult(stage=StageName.MERGE, error="ticket_closed")
       if reason := gating.check(ctx, event):
           return DispatchResult(stage=reason.stage, blocked=True, error=reason.reason)

       intent = ingress.resolve_intent(ctx, event)
       ctx.intent = intent
       pr_number = _ensure_draft_pr(ctx, intent)
       ctx.pr_number = pr_number
       # ... prepare comment + stage_config + telemetry envelope
       return await _run_attempted_stage(ctx, intent, ...)
   ```
   Anything that doesn't fit moves to `ingress` or `gating`.
   Target LOC: dispatch.py ≤ 80, `_run_attempted_stage` ≤ 40.

9. **Delete `preflight.py`.**
   By step 8 nothing imports it except legacy tests. Either migrate
   tests to call `ingress.resolve_intent` directly or retain a
   shim `run_preflight` that composes `parse_event → gating.check →
   resolve_intent`. Whichever is shorter — decide when the change
   lands.

### D. Closure

10. **Update P4 spec status to Executed. RFC-0001 + pitch stay.**

## File-level changes

| File | Change |
|---|---|
| `packages/engine/src/a2sdlc/pipeline/ingress.py` | **New** — `parse_event`, `resolve_intent`. |
| `packages/engine/src/a2sdlc/pipeline/gating.py` | **New** — `check(ctx, event) -> BlockReason | None`. |
| `packages/engine/src/a2sdlc/domain/run_intent.py` | **New** — `RunIntent` dataclass. |
| `packages/engine/src/a2sdlc/domain/run_context.py` | **New** — `RunContext` dataclass (narrow). |
| `packages/engine/src/a2sdlc/pipeline/dispatch.py` | Modified — collapses to ~80 LOC composition root. |
| `packages/engine/src/a2sdlc/pipeline/preflight.py` | **Deleted** at step 9. |
| `packages/engine/src/a2sdlc/pipeline/feedback_routing.py` | Moved under `ingress/` as helper (or kept — decide). |
| `tests/pipeline/test_ingress.py` | **New** — L1 + L2 for parse + resolve. |
| `tests/pipeline/test_gating.py` | **New** — L1 per rule. |
| `tests/domain/test_run_intent.py` | **New** — L1. |
| `tests/pipeline/test_dispatch*.py` | Modified — dispatch orchestration assertions adapt. |

## Test strategy

- **L1 Unit.** Every new entry point (ingress.parse_event,
  ingress.resolve_intent, each gating rule) has focused unit tests.
  `RunIntent` + `RunContext` dataclasses get minimal round-trip tests.
- **L2 Contract.** Existing dispatch integration tests stay green —
  they're the end-to-end safety net for the refactor.
- **L3 Integration.** Cassette-backed GitHub adapter tests untouched.
- **L4 Real-platform.** No re-recording needed — no external API
  surface changes.
- **L5 Event replay.** No change.
- **L6 E2E smoke.** Run after step 8 before declaring P4 done.
- **L7 Eval.** Not yet — P4 is structural.

## Security considerations

- **No new external surface.** All changes are internal reshapes.
- **Ordering guarantees.** gating.check runs in a deterministic order
  (ticket-active → idempotency → breakers); the order matters for the
  "blocked reason" we surface to telemetry. Tests pin it.
- **Idempotency still centralized.** Not yet a middleware; P5's job.
  Preserve today's semantics: same `run_id` → early return with
  "duplicate_run_id" label.

## Rollout

Ships on main one step at a time. Highest-risk step is **step 8**
(dispatch.py collapse) — this is where the full reshape lands and
where any latent coupling between preflight and the rest surfaces.
Run the full pytest suite + cassette tier + L6 smoke after step 8.

Steps 1–7 are additive or pure rename: each ships with the existing
dispatch path still working via `run_preflight`. The old path removal
lives in step 8 alone.

Not feature-flagged. Composition changes don't benefit from runtime
toggles.

## Backout

Steps 1–4 are pure additions; trivially revertible.
Step 5 (dispatch switches to the new modules) is the first behavior-
equivalent point; revert if dispatch tests fail.
Steps 6–7 are alias introductions; no behavior change.
Step 8 (collapse) is the load-bearing commit. If it ships broken,
revert that single commit and the prior state is clean: the new
modules still exist and `run_preflight` still calls them; only the
composition root reverts to its verbose form.
Step 9 (preflight delete) is easy to back out (re-add the file).

## Links

- RFC: [../../rfcs/0001-v1-scope.md](../../rfcs/0001-v1-scope.md)
- Pitch: [../../pitches/2026-04-23-v1-scope.md](../../pitches/2026-04-23-v1-scope.md)
- Architecture vision §7.1 (package layout)
- Architecture vision §7.3 (composition-root shape — the P4 target)
- P3 spec (prerequisite): `2026-04-25-p3-effects-adt-design.md`
