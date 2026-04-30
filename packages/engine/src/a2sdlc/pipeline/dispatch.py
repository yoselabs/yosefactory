"""Dispatch — composition root for one pipeline run.

Reads as pseudocode per architecture vision §7.3: ingress parses the
event, gating admits it, ingress resolves intent, then we wire per-run
state onto ``ctx`` and hand off to the stage-attempt middleware stack.
Each AI stage (and MERGE since P2 step 8) owns its own ``execute()``;
this file wires them together and hands off to the middleware onion
(telemetry today; P5 step 4 adds idempotency).
"""

from __future__ import annotations

from a2sdlc.config import load_stage_config
from a2sdlc.domain.models import StageName
from a2sdlc.domain.run_context import RunContext
from a2sdlc.domain.run_intent import RunIntent
from a2sdlc.domain.run_result import DispatchResult
from a2sdlc.domain.stats import StageRunStats
from a2sdlc.lifecycle.comment import CommentManager
from a2sdlc.lifecycle.pr import PRLifecycle
from a2sdlc import ingress
from a2sdlc import gating
from a2sdlc.effects.apply import apply as apply_effects
from a2sdlc.middleware.idempotency import with_idempotency
from a2sdlc.middleware.telemetry import with_telemetry
from a2sdlc.effects.stage_finish import outcome_to_dispatch_result
from a2sdlc.pipeline.stage_executor import StageExecutor
from a2sdlc.stages import get_stage


async def dispatch(ctx: RunContext) -> DispatchResult:
    """Run one pipeline stage. Returns what happened.

    Wraps the run loop in try/except/finally so ``RunEnd`` is emitted on
    every terminal exit path — handled returns, blocked outcomes, AND
    unhandled exceptions (spec §Console output cadence, AC #14). The
    finally block is best-effort and never raises.
    """
    success = True
    error: str | None = None
    try:
        return await _dispatch_body(ctx)
    except Exception as exc:
        success = False
        error = str(exc) or exc.__class__.__name__
        raise
    finally:
        try:
            await _emit_run_end(ctx, success=success, error=error)
        except Exception:  # noqa: BLE001
            ctx.logger.exception("dispatch.run_end_emit_failed")


async def _dispatch_body(ctx: RunContext) -> DispatchResult:
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
    ctx.stage_executor = StageExecutor(ctx.runner)
    _wire_comment_and_subscriber(ctx, intent)

    stack = with_idempotency(with_telemetry(run_stage))
    return await stack(ctx, intent)


async def _emit_run_end(ctx: RunContext, *, success: bool, error: str | None) -> None:
    """Emit terminal ``RunEnd`` via ``ctx.progress_state``.

    Best-effort: resolves ``workflow_id`` from whichever per-run field
    is populated, and falls back to empty stats/cycles when state.json
    is unreadable or hasn't been authored with the v1 fields yet
    (loader lands in Task 17/18).
    """
    workflow_id = _resolve_workflow_id(ctx)
    aggregate = StageRunStats()
    cycles: dict[StageName, int] = {}
    try:
        raw = ctx.git.read_state() if ctx.git is not None else None
        if raw:
            import json

            data = json.loads(raw)
            agg = data.get("aggregate_stats") or {}
            aggregate = StageRunStats(
                cost_usd=float(agg.get("cost_usd", 0) or 0),
                tokens_in=int(agg.get("tokens_in", 0) or 0),
                tokens_out=int(agg.get("tokens_out", 0) or 0),
                duration_ms=int(agg.get("duration_ms", 0) or 0),
                num_turns=int(agg.get("num_turns", 0) or 0),
            )
            raw_cycles = data.get("total_cycles") or {}
            for name, count in raw_cycles.items():
                try:
                    cycles[StageName(name)] = int(count)
                except (ValueError, TypeError):
                    continue
    except Exception:  # noqa: BLE001
        # State unreadable / wrong shape — fall back to defaults.
        pass

    if ctx.progress_state is None:
        return
    await ctx.progress_state.run_end(
        workflow_id=workflow_id,
        success=success,
        error=error,
        aggregate_stats=aggregate,
        total_cycles=cycles,
    )


def _resolve_workflow_id(ctx: RunContext) -> str:
    """Best-effort workflow_id resolution.

    Order: ``ctx.run.workflow_id`` (the canonical PipelineRun identity)
    → ``ctx.intent.branch`` (populated once ingress resolves intent)
    → empty string. Never raises.
    """
    run = getattr(ctx, "run", None)
    if run is not None:
        wid = getattr(run, "workflow_id", "") or ""
        if wid:
            return wid
    intent = getattr(ctx, "intent", None)
    if intent is not None:
        branch = getattr(intent, "branch", "") or ""
        if branch:
            return branch
    return ""


def _ensure_draft_pr(ctx: RunContext, intent: RunIntent) -> int | None:
    """Return the PR number, creating a draft on SPEC if none exists.

    GitHub rejects PRs against unpushed branches and empty-diff PRs —
    seed an empty commit, push, then open.

    The branch-match guard on ``state.pr_number`` defends against state
    leaking onto base branches: if the engine's MERGE stage is bypassed
    (manual merge in the GitHub UI, or merge from CLI without
    ``strip_runtime_state``), ``.a2sdlc/state/state.json`` survives onto
    the base. The next SPEC dispatch then inherits a stale
    ``pr_number`` belonging to a previous ticket and refuses to open a
    new draft. We only trust the cached PR number when the state was
    written for *this* branch.
    """
    state = intent.state
    state_owns_branch = state is not None and state.branch == intent.branch
    pr_number = state.pr_number if state_owns_branch and state else None
    ctx.logger.debug(
        "dispatch.ensure_draft_pr.entry",
        extra={
            "target_stage": intent.target_stage.value,
            "state_present": state is not None,
            "state_branch": state.branch if state else None,
            "intent_branch": intent.branch,
            "state_owns_branch": state_owns_branch,
            "pr_number_used": pr_number,
            "event_pr_number": intent.event.pr_number,
        },
    )
    if intent.target_stage == StageName.SPEC and pr_number is None:
        ctx.logger.debug("dispatch.ensure_draft_pr.creating")
        ctx.git.commit_empty(f"chore(a2sdlc): open session for {intent.event.key}")
        ctx.git.push()
        pr_number = ctx.pr_lifecycle.create_draft(
            intent.branch, intent.base, intent.event.key
        )
        ctx.logger.info("dispatch.draft_pr_created", extra={"pr": pr_number})
    if intent.event.pr_number is not None:
        pr_number = intent.event.pr_number
    return pr_number


def _wire_comment_and_subscriber(ctx: RunContext, intent: RunIntent) -> None:
    """Start the stage comment and subscribe the comment-driving subscriber."""
    comment = CommentManager(ctx.work, intent.event.key)
    comment.start(intent.target_stage.value)
    ctx.comment = comment
    if ctx.make_comment_subscriber is not None:
        ctx.progress_state.subscribe(ctx.make_comment_subscriber(comment))


async def run_stage(ctx: RunContext, intent: RunIntent) -> DispatchResult:
    """Pure stage-attempt unit — handler + effects + result.

    The innermost call of the middleware stack. Telemetry/progress
    envelopes and idempotency short-circuits live in middleware that
    wraps this function.
    """
    handler = get_stage(intent.target_stage)
    outcome = await handler.execute(ctx)
    await apply_effects(ctx, handler.effects(ctx, outcome))
    return outcome_to_dispatch_result(intent, outcome)


__all__ = ["dispatch"]
