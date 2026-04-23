---
title: "P3 — Effects ADT + interpreter"
type: spec
status: Executed
owner: "@iorlas"
created: 2026-04-25
updated: 2026-04-25
rfc: "../../rfcs/0001-v1-scope.md"
pitch: "../../pitches/2026-04-23-v1-scope.md"
author:
  human: "@iorlas"
  agent: "claude-opus-4-7 (V1.0 execution session 2026-04-25)"
---

# P3 — Effects ADT + interpreter

## Goal

Move side-effect emission out of `StageHandler.execute()` into the pure
`effects(ctx, outcome) -> list[Effect]` method (architecture vision
§7.2). Introduce the `Effect` ADT with the V1.0 arms listed in
RFC-0001 §Data model. Introduce an interpreter (`effects/interpreter.py`)
that pattern-matches variants against adapter calls — dispatch calls
it once per run after `execute()`.

This is the "big unlock" for the engine: side effects become data —
logged, replayable, auditable (architecture vision §7.2 and §P6). It
collapses the four copy-pasted error-comment blocks (SPEC / IMPLEMENT /
REVIEW / MERGE all write `comment.finalize(...) → mark_blocked(...)`
inline today) into one interpreter arm. It unblocks N4 (`RunSecretsScan`
effect) and the MLflow artifact-log work in P8.

**P3 does NOT touch the middleware onion (§7.4), the pipeline.py
composition root rewrite (§7.3), or introduce `RunContext`.** Those are
P4 / P6 concerns. In P3, dispatch still drives the pipeline; it just
gains an interpreter call after `handler.execute()`.

Third V1.0 migration-phase spec. Appetite: **1.5–2 weeks.**

## Non-goals

- **No pipeline.py composition-root rewrite.** `pipeline/dispatch.py`
  keeps its shape. Only the per-run "apply effects" call is new.
- **No `RunContext` introduction.** `DispatchContext` stays the ctx
  type; P4 narrows it. Handlers read per-run state off it as today.
- **No middleware onion (§7.4).** Idempotency / retry / logging /
  telemetry stay where they are.
- **No Event ADT adoption.** P1 landed the types; call-site migration
  is P4.
- **No effects persistence / replay.** RFC-0001 Q2 ("effects transient
  per Q2") holds — the interpreter applies and forgets. Audit-log work
  is a P8 / H2 concern.
- **No new adapter methods.** All V1.0 arms map onto existing adapter
  methods (`WorkAdapter.mark_blocked`, `PRLifecycle.post_review`,
  `GitAdapter.commit_artifacts`, …). No new external API surface.
- **No removal of `StageOutcome.blocked` / `error` in the first
  migration steps.** They flip to pure "the handler decided this run
  was blocked" markers consumed by `effects()`; step 9 collapses them
  after every handler is migrated and we're sure no one outside the
  handler reads them.

## Plan

Each step = one commit. 11 steps grouped into 4 stages. Each step must
leave `make check` green.

### A. Pure additions (safe, land first)

1. **`Effect` ADT — V1.0 arms only.**
   New `domain/effects.py`. One frozen dataclass per arm, union-typed
   as `Effect`. V1.0 arm set (from RFC-0001 §Data model):
   - Session lifecycle: `StateWrite(state)`, `CommentFinalize(body)`,
     `PostReview(pr, verdict, body)`, `PostInlineReview(pr, comments)`,
     `SetCurrentStage(stage)`, `MarkBlocked(reason)`, `MarkDone`,
     `MarkNeedsInput`.
   - Git: `CommitAndPush(paths, message)`.
   - Control flow: `Transition(next: StageName | None)`.
   - Quality / eval: `LogMetric(key, value)`, `LogArtifact(path)`.
   `CommentStart`, `CreateDraftPR`, `UpdatePR`, `MergePR`, `CleanupBase`,
   `RunQualityGate`, `RunSecretsScan` are **registered in the ADT** but
   have **no interpreter arm yet** — they land with their respective
   callers (N4 for `RunSecretsScan`, P5/P6 for the rest).
   *L1 tests:* each arm constructs + round-trips through its frozen
   dataclass; the union types correctly under `match`.

2. **`effects/` package — interpreter skeleton.**
   New `pipeline/effects/interpreter.py` (or `effects/interpreter.py` —
   pick the package that keeps domain-purity CI green; likely
   `pipeline/` since the interpreter touches adapters).
   Shape:
   ```python
   async def apply(ctx: DispatchContext, effects: list[Effect]) -> None:
       for eff in effects:
           match eff:
               case MarkBlocked(reason): ctx.work.mark_blocked(ctx.pre.event.key, reason)
               case MarkDone(): ctx.work.mark_done(ctx.pre.event.key)
               ...
   ```
   Each arm maps to exactly one adapter call. No branching inside arms
   — if a handler needs conditional behavior, it emits different
   effects.
   *L1 tests:* one test per interpreter arm using fake adapters;
   verifies the correct adapter method is invoked with the correct
   arguments.

3. **Wire interpreter into dispatch (no-op for now).**
   `pipeline/dispatch.py::_run_attempted_stage` gains:
   ```python
   outcome = await handler.execute(ctx)
   effects = handler.effects(ctx, outcome)
   await apply(ctx, effects)
   result, success, error = _outcome_to_dispatch_tuple(pre, outcome)
   ```
   Every handler's `effects()` still returns `[]` in this step, so the
   apply call is a no-op. Lands the seam.
   *L2 test:* an integration test asserts that when a handler returns
   a non-empty `effects()` list, each one fires against the adapter.
   Uses a test-only stub handler.

### B. Per-handler migration (one handler per step)

Each migration moves the inline `ctx.work.*` / `ctx.git.*` /
`pr_lifecycle.*` / `comment.finalize(...)` calls out of `execute()`
into the `effects()` return. `execute()` becomes a pure function
(except for the AI call itself — the `StageExecutor` is the one
non-removable I/O, since the agent output drives the outcome).

4. **`SpecStage`: migrate to `effects()`.**
   `execute()` keeps its AI call (via `StageExecutor`) and its shape
   for prompt assembly + failure-mode detection. Every other adapter
   call (commit_and_push, state write, comment finalize, mark_blocked,
   set_current_stage, log_metric) moves to the returned effect list.
   The three outcome shapes (failure, no-status-block, success) map to
   three effect-list shapes.
   *L2 test:* the N6 standalone test updates — instead of asserting
   work/git fake call counts, it asserts the returned effect list
   contains the expected variants.

5. **`ImplementStage`: migrate to `effects()`.**
   Same pattern as step 4.

6. **`ReviewStage`: migrate to `effects()`.**
   Same pattern, plus: the `post_review` + `post_inline_comments` calls
   become `PostReview` + `PostInlineReview` effect variants.

7. **`MergeStage`: migrate to `effects()`.**
   MERGE is the most side-effect-heavy handler. `execute()` reduces to
   the gate checks (no PR → return blocked outcome; HUMAN gate no
   approval → return blocked outcome; approved → return success
   outcome). The actual merge sequence (sync_with_base,
   strip_runtime_state, update_title, merge, mark_done,
   comment.finalize) becomes an effect list. The `merge_pr` call is
   itself an effect (`MergePR(pr)` — needs its own interpreter arm, so
   add it in this step, not step 1).

### C. Error-path collapse

8. **Collapse the four error-comment blocks.**
   Today SPEC / IMPLEMENT / REVIEW / MERGE each build their own
   `format_error(...)` → `comment.finalize(...)` → `mark_blocked(...)`
   triple. After step 7 all four live in `effects()`, but they're
   still duplicated. Extract into one helper:
   ```python
   def blocked_effects(pre, exec_result, reason) -> list[Effect]: ...
   ```
   in `stages/_shared.py` (or similar). Handlers call it; the
   interpreter stays uniform. Drops ~60 LOC per handler.

9. **Drop `StageOutcome.blocked` + `error` — let effects carry it.**
   After step 8, dispatch's `_outcome_to_dispatch_tuple` only reads
   `status` / `merged` / `next_stage_hint`. The `blocked` / `error`
   fields on `StageOutcome` are redundant — `effects()` already emits
   `MarkBlocked` + `CommentFinalize` on the blocked path. Remove the
   fields; dispatch reads blocked-ness from the outcome's status +
   merged slots.

   **Execution reshape.** The plan assumed `MarkBlocked` covered every
   non-advance case. MergeStage's HUMAN-gate wait breaks that: the
   ticket is *paused for a human*, not *blocked on the platform* — no
   `MarkBlocked` emitted. Added a new first-class arm
   `AwaitHumanDecision(kind, reason)` as the HITL primitive (future
   home for dashboard notifications, Slack routing, SLA tracking).
   Dispatch's `_pipeline_pause_reason(effects)` scans for
   `MarkBlocked | AwaitHumanDecision`. SPEC / IMPLEMENT QUESTIONS
   paths also emit it alongside `MarkNeedsInput`, unifying the "human
   must decide for the pipeline to advance" concept across stages.

### D. Type tightening + closure

10. **`StageHandler.effects()` return type: `list[Effect]`.**
    The Protocol in `stages/handler.py` currently types it as
    `list[object]` (P2 transitional). Flip to `list[Effect]` and fix
    the one `type: ignore` that surfaces.

11. **Update P3 spec status to Executed. RFC-0001 + pitch stay.**

## File-level changes

| File | Change |
|---|---|
| `packages/engine/src/a2sdlc/domain/effects.py` | **New** — `Effect` ADT + V1.0 arm dataclasses. |
| `packages/engine/src/a2sdlc/pipeline/effects_apply.py` | **New** — interpreter (`apply(ctx, effects)`). |
| `packages/engine/src/a2sdlc/pipeline/dispatch.py` | Modified — one new call: `await apply(ctx, handler.effects(ctx, outcome))`. |
| `packages/engine/src/a2sdlc/stages/spec.py` | Modified — side effects move to `effects()`. |
| `packages/engine/src/a2sdlc/stages/implement.py` | Modified — same. |
| `packages/engine/src/a2sdlc/stages/review.py` | Modified — same; + `PostInlineReview`. |
| `packages/engine/src/a2sdlc/stages/merge.py` | Modified — same. |
| `packages/engine/src/a2sdlc/stages/_shared.py` | **New** — `blocked_effects(...)` helper after step 8. |
| `packages/engine/src/a2sdlc/stages/handler.py` | Modified — `effects()` return type tightens. |
| `packages/engine/src/a2sdlc/domain/stage_outcome.py` | Modified — drop `blocked` + `error` in step 9. |
| `tests/domain/test_effects.py` | **New** — L1 tests per ADT arm. |
| `tests/pipeline/test_effects_apply.py` | **New** — L1 tests per interpreter arm. |
| `tests/stages/test_*.py` | Modified — N6 tests assert effect lists instead of adapter call counts. |

## Test strategy

- **L1 Unit.** Each `Effect` arm constructs + is pattern-matchable.
  Each interpreter arm invokes the right adapter method.
  Each handler's `effects()` emits the right list for each outcome shape.
- **L2 Contract.** `StageHandler` conformance suite re-runs with the
  tightened `effects()` return type. A property-style test: for every
  outcome shape, the effect list applied against fake adapters
  produces the same adapter-call trace as the pre-migration handler.
- **L3 Integration.** Existing dispatch integration tests stay green;
  the observable behavior from outside the pipeline is unchanged.
- **L4 Real-platform.** No new cassettes needed — `PostInlineReview`
  already has a cassette from P2 step 4. Re-record if interpreter
  sequencing changes the call order.
- **L5 Event replay.** No change — event parsing untouched.
- **L6 E2E smoke.** The smoke workflow runs untouched; if it passes,
  the refactor preserves externally-observable behavior.
- **L7 Eval.** Not yet — P3 is structural, not prompt-changing.

## Security considerations

- **Tokens / secrets touched:** none new. All effects map to existing
  adapter methods whose auth paths are unchanged.
- **Ordering guarantees:** the interpreter applies effects in list
  order. Handlers must emit effects in the order their side effects
  should land. This matters for `CommentFinalize` vs `MarkBlocked` —
  if the comment fails, we still mark blocked; emit blocked first so
  a partial failure doesn't leave a ticket stuck "in-progress" with a
  half-written comment.
- **Partial failure in interpreter:** the interpreter short-circuits
  on the first exception — no silent partial application. The `try`
  block in `dispatch._run_attempted_stage` already converts an
  interpreter crash into an `unknown` StageEnd, which is the right
  behavior (we want the crash to surface, not be swallowed).
- **Abuse modes:** no new surface. Effects are produced by handlers,
  whose prompts are already trusted in the N9 interim posture. An
  effect list is as trustworthy as the handler that emits it.
- **Idempotency:** effects are not idempotent by default — a retried
  run replays `MarkBlocked` / `CommentFinalize` against the same
  ticket. This matches today's behavior (the inline calls in execute()
  are equally non-idempotent). Idempotency keys + `IdempotencyStore`
  effect are a P6 / middleware concern.

## Rollout

Ships on the V1.0 refactor branch one step at a time. The load-bearing
points are:

- **After step 3** — the interpreter is wired but all effect lists are
  empty. Any regression here is in the interpreter itself or dispatch
  wiring. Full pytest suite + cassette tier green required.
- **After step 7** — all four handlers migrated. This is the largest
  behavior-preserving refactor in V1.0. The cassette tier is the
  primary safety net: if a recorded GitHub interaction still replays
  cleanly, externally-observable behavior is preserved.
- **After step 9** — `StageOutcome` narrows. Any code outside handlers
  that read `outcome.blocked` / `outcome.error` now breaks at ty; fix
  surface-by-surface, don't silently catch.

Not feature-flagged — effects migration is structural, not optional.

## Backout

Steps A (1–3) are pure additions; trivially revertible. Steps B (4–7)
migrate behavior per-handler; each ships green so reverting one keeps
the previous green. Step 8 (helper extraction) is pure refactor —
trivially revertible. Step 9 (StageOutcome narrowing) is the hardest
to back out because it removes fields; if a consumer we missed reads
them, revert the commit and add them back with a deprecation marker
before retrying.

## Links

- RFC: [../../rfcs/0001-v1-scope.md](../../rfcs/0001-v1-scope.md)
- Pitch: [../../pitches/2026-04-23-v1-scope.md](../../pitches/2026-04-23-v1-scope.md)
- Architecture vision §7.2 (StageHandler + Effect ADT)
- Architecture vision §P6 (auditable effects rubric)
- P2 spec (prerequisite): `2026-04-24-p2-stage-handlers-design.md`
