---
title: "P5 — Middleware layer"
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

# P5 — Middleware layer

## Goal

Extract the two cross-cutting concerns currently tangled in dispatch
— **idempotency** (the `check_duplicate_run_id` call buried inside
`ingress.resolve_intent`) and **telemetry framing** (the MLflow
session + stage context managers + `progress_state.stage_start`/
`stage_end` envelope inside `_run_attempted_stage`) — into a composable
middleware stack wrapping the stage-attempt unit.

After P5:

- `pipeline/dispatch.py` ends with one line that composes the stack:
  `stack = with_idempotency(with_telemetry(run_stage))`.
- `_run_attempted_stage` dissolves; in its place is a pure `run_stage`
  helper (~5 LOC) that runs the handler, applies effects, returns a
  `DispatchResult`.
- Each middleware is a single async function with an L1 test suite
  that uses a fake `next_`.

V1.0 success criterion: the middleware composition line is visible at
a single call site, and each cross-cutting concern can be added, removed,
or reordered without touching `dispatch()`.

Fifth V1.0 migration-phase spec. Appetite: **3 days.**

## Non-goals

- **No `CompositionProfile`.** P6 owns declarative middleware wiring.
  P5 keeps hand-wired composition at one call site in dispatch.
- **No retry middleware.** No call site needs it today — adapter-level
  retries already exist in the GitHub adapters. Adding a speculative
  middleware layer before a concrete caller is YAGNI.
- **No logging middleware.** Ambient `ctx.logger` usage is fine for
  V1.0. Extracting logging into a middleware would be a style-only
  reshape without a behavior payoff.
- **No idempotency persistence change.** The middleware reads the
  existing `StateManager.check_idempotency(run_id)` path via
  `intent.state_mgr`. No new run-ledger, no new storage layer.
  Vision §7.4 shows idempotency wrapping all of `dispatch()`; the
  honest boundary for V1.0 is the stage-attempt unit (idempotency
  needs `intent` to exist, so it cannot precede ingress).
- **No module relocations beyond the new subpackage.** `pipeline/`
  stays as the home of middleware/, ingress, gating, dispatch until
  P7 relocates them.
- **No changes to `StageHandler` Protocol or `Effect` ADT.**

## Plan

Each step = one commit. 5 steps. Each step must leave `make check`
green.

1. **Extract `run_stage` inside `dispatch.py`.**
   Replace `_run_attempted_stage`'s body with a local `run_stage(ctx,
   intent)` that does handler resolution + execute + effects + result.
   Telemetry session + progress envelope stay in a local wrapper
   `_with_telemetry_inline` during this step. Tuple returned from
   `stage_finish.outcome_to_dispatch_tuple` is unpacked in that
   wrapper. **No behavior change; no new package.** Existing tests stay
   green.

2. **Add `pipeline/middleware/` package skeleton.**
   New `pipeline/middleware/__init__.py` with the `StageAttempt` +
   `Middleware` type aliases:
   ```python
   StageAttempt = Callable[[RunContext, RunIntent], Awaitable[DispatchResult]]
   Middleware  = Callable[[StageAttempt], StageAttempt]
   ```
   No middleware bodies yet. L1 import smoke test asserts the aliases
   are importable.

3. **Extract `with_telemetry` → `pipeline/middleware/telemetry.py`.**
   Move the inline telemetry wrapper from dispatch into the middleware.
   Derive `(success, error)` from the returned `DispatchResult` — drop
   the tuple contract. `stage_finish.outcome_to_dispatch_tuple` →
   `outcome_to_dispatch_result` returning just `DispatchResult`. Update
   `stage_finish` L1 tests. Dispatch now composes
   `with_telemetry(run_stage)`.
   *L1 tests:* passthrough; `ctx.run` is set to the run handle before
   `next_` is awaited; `progress_state.stage_start`/`stage_end`
   are called exactly once; tags are logged; `success=False, error=<reason>`
   are extracted from a blocked `DispatchResult`.

4. **Extract `with_idempotency` → `pipeline/middleware/idempotency.py`.**
   Move the `check_duplicate_run_id` call out of
   `ingress.resolve_intent` into the middleware. `resolve_intent` loses
   the call + the `check_duplicate_run_id` import. The helper itself
   stays in `pipeline/gating.py` as pure decision logic (the middleware
   is the sole caller in V1.0; `gating.check_duplicate_run_id` is still
   a legitimate standalone primitive that N+1 future middleware could
   re-use).
   Dispatch composes `with_idempotency(with_telemetry(run_stage))`.
   *L1 tests:* duplicate short-circuits with `error="duplicate_run_id"`;
   non-duplicate passes through to fake `next_`; `None` run_id is a
   no-op pass-through.
   *L2 composition test:* idempotency short-circuits **before**
   telemetry opens a session — verify the composed stack produces no
   progress or MLflow calls on a dupe.

5. **Spec status → Executed.** Update RFC cross-ref if needed.

## File-level changes

| File | Change |
|---|---|
| `packages/engine/src/a2sdlc/pipeline/middleware/__init__.py` | **New** — type aliases, re-exports. |
| `packages/engine/src/a2sdlc/pipeline/middleware/idempotency.py` | **New** — `with_idempotency`. |
| `packages/engine/src/a2sdlc/pipeline/middleware/telemetry.py` | **New** — `with_telemetry`. |
| `packages/engine/src/a2sdlc/pipeline/dispatch.py` | Modified — `_run_attempted_stage` deleted; `run_stage` helper; one-line stack compose. |
| `packages/engine/src/a2sdlc/pipeline/stage_finish.py` | Modified — `outcome_to_dispatch_result` returns `DispatchResult`; tuple dance gone. |
| `packages/engine/src/a2sdlc/pipeline/ingress.py` | Modified — drop `check_duplicate_run_id` call + import. |
| `packages/engine/src/a2sdlc/pipeline/gating.py` | Unchanged — `check_duplicate_run_id` stays as a pure decision helper; middleware is the sole caller in V1.0. |
| `tests/pipeline/middleware/test_idempotency.py` | **New** — L1. |
| `tests/pipeline/middleware/test_telemetry.py` | **New** — L1. |
| `tests/pipeline/middleware/test_composition.py` | **New** — L2. |
| `tests/pipeline/test_stage_finish.py` | Modified — adapt to singular-return shape. |

## Target shapes

### Interface (in `pipeline/middleware/__init__.py`)

```python
from collections.abc import Awaitable, Callable

from a2sdlc.domain.run_context import RunContext
from a2sdlc.domain.run_intent import RunIntent
from a2sdlc.domain.run_result import DispatchResult

StageAttempt = Callable[[RunContext, RunIntent], Awaitable[DispatchResult]]
Middleware  = Callable[[StageAttempt], StageAttempt]
```

### `with_idempotency` body

```python
def with_idempotency(next_: StageAttempt) -> StageAttempt:
    async def run(ctx: RunContext, intent: RunIntent) -> DispatchResult:
        if ctx.run_id and intent.state_mgr.check_idempotency(ctx.run_id):
            ctx.logger.info("dispatch.duplicate_run_id", extra={"run_id": ctx.run_id})
            return DispatchResult(stage=intent.target_stage, error="duplicate_run_id")
        return await next_(ctx, intent)
    return run
```

### `with_telemetry` body

```python
def with_telemetry(next_: StageAttempt) -> StageAttempt:
    async def run(ctx: RunContext, intent: RunIntent) -> DispatchResult:
        stage_config = ctx.stage_config
        session_id = f"{intent.event.key}:{ctx.run_id or uuid.uuid4()}"
        telemetry = ctx.telemetry or NoopTelemetry()
        with (
            telemetry.session(session_id) as opener,
            opener.stage(intent.target_stage.value) as run_handle,
        ):
            run_handle.log_tag("ticket_key", intent.event.key)
            run_handle.log_tag("target_stage", intent.target_stage.value)
            await ctx.progress_state.stage_start(
                intent.target_stage, session_id,
                model=stage_config.model,
                max_turns=stage_config.max_turns,
                context_window=context_window_for_model(stage_config.model) or 0,
                branch=intent.branch,
            )
            result = DispatchResult(stage=intent.target_stage, error="unknown")
            try:
                ctx.run = run_handle
                result = await next_(ctx, intent)
                return result
            finally:
                await ctx.progress_state.stage_end(
                    intent.target_stage,
                    success=(not result.blocked and result.error is None),
                    error=result.error,
                    final=ctx.progress_state.snapshot_metrics(),
                )
    return run
```

### `run_stage` (inside `dispatch.py`)

```python
async def run_stage(ctx: RunContext, intent: RunIntent) -> DispatchResult:
    handler = get_stage(intent.target_stage)
    outcome = await handler.execute(ctx)
    await apply_effects(ctx, handler.effects(ctx, outcome))
    return outcome_to_dispatch_result(intent, outcome)
```

### Dispatch after P5

```python
async def dispatch(ctx: RunContext) -> DispatchResult:
    parsed = ingress.parse_event(ctx)
    if isinstance(parsed, ingress.ParsedSkip):
        return DispatchResult(stage=StageName.SPEC, error=parsed.reason)
    event = parsed
    if event.is_closed:
        ctx.logger.info("dispatch.ticket_closed", extra={"key": event.key})
        ctx.work.mark_done(event.key)
        return DispatchResult(stage=StageName.MERGE, error="ticket_closed")
    if reason := gating.check(ctx, event):
        return DispatchResult(stage=StageName.SPEC, error=reason)

    intent = ingress.resolve_intent(ctx, event)
    if isinstance(intent, DispatchResult):
        return intent

    ctx.intent = intent
    ctx.pr_lifecycle = PRLifecycle(ctx.review)
    ctx.pr_number = _ensure_draft_pr(ctx, intent)
    ctx.stage_config = load_stage_config(intent.target_stage.value, ctx.config)
    _wire_comment_and_subscriber(ctx, intent)

    stack = with_idempotency(with_telemetry(run_stage))
    return await stack(ctx, intent)
```

## Test strategy

- **L1 Unit — each middleware.** Fake `next_`
  (`async def fake(ctx, intent): return DispatchResult(...)`).
  Assert passthrough, short-circuit, ctx mutation (telemetry sets
  `ctx.run`), side effects (telemetry calls `stage_start`/`stage_end`
  once, opens one session, logs tags).
- **L1 Unit — `run_stage`.** Direct call with a fake handler that
  returns a canned `StageOutcome`. Assert effects applied, result
  shape matches `outcome_to_dispatch_result(intent, outcome)`.
- **L1 Unit — `stage_finish.outcome_to_dispatch_result`.** Existing
  tests adapt to the singular-return shape. Pause, merged, and AI
  happy-path arms all still covered.
- **L2 Contract — composition.** `with_idempotency(with_telemetry(fake_next))`
  against `tests/fakes`. On a dupe run_id, assert no
  `progress_state.stage_start` was called and no telemetry session
  opened — the idempotency short-circuit happens outside the telemetry
  layer.
- **L3 Integration — existing dispatch e2e + cassettes.** Unchanged
  assertions. Middleware is a refactor, not a behavior change. Run
  `make test-integration` after step 4.

## Security considerations

- **No new external surface.** All changes are internal reshapes.
- **Idempotency semantics preserved.** Still keyed on `(state_mgr,
  run_id)`, still short-circuits before any adapter mutation. No
  change to what "duplicate" means.
- **Telemetry session ordering preserved.** `ctx.run = run_handle`
  is set *before* `next_(ctx, intent)` is awaited, so `LogMetric`
  effects emitted from the handler continue to see a valid run handle.

## Rollout

Ships on main one step at a time. Highest-risk step is **step 4**
(idempotency extraction) — the call site moves from `ingress` to the
composed middleware stack, and a test regression there would show up
as "duplicate runs now execute instead of short-circuiting." The L1
+ L2 tests pin this.

Steps 1–3 are mechanical: step 1 is internal rearrangement inside
dispatch; step 2 adds an empty package; step 3 moves code from one
file to another with identical semantics. Step 5 is documentation.

Not feature-flagged. Composition changes don't benefit from runtime
toggles.

## Backout

Each step is independent and revertible.

- Step 1 revert: inline the `run_stage` body back into `_run_attempted_stage`.
- Step 2 revert: delete the empty package.
- Step 3 revert: move telemetry back inline; restore the tuple shape.
  `stage_finish` diff is one function signature; mechanical.
- Step 4 revert (the load-bearing commit): re-add the
  `check_duplicate_run_id` call to `resolve_intent`, delete the
  idempotency middleware. The middleware package stays (no harm) or
  is deleted if desired.
- Step 5 revert: flip the spec status back.

## Links

- RFC: [../../rfcs/0001-v1-scope.md](../../rfcs/0001-v1-scope.md)
- Architecture vision §7.4 (middleware onion — the P5 target)
- P4 spec (prerequisite): `2026-04-25-p4-pipe-and-filter-design.md`
