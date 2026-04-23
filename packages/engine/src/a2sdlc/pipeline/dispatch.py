"""Dispatch — composition root for one pipeline run.

Reads as pseudocode per architecture vision §7.3: ingress parses the
event, gating admits it, ingress resolves intent, then we wire per-run
state onto ``ctx`` and hand off to the stage handler under telemetry.
Each AI stage (and MERGE since P2 step 8) owns its own ``execute()``;
this file wires them together and owns the ``stage_end`` contract.
"""

from __future__ import annotations

import uuid

from a2sdlc.config import load_stage_config
from a2sdlc.domain.models import StageName
from a2sdlc.domain.progress_format import context_window_for_model
from a2sdlc.domain.run_context import RunContext
from a2sdlc.domain.run_intent import RunIntent
from a2sdlc.domain.run_result import DispatchResult
from a2sdlc.evaluation.telemetry import NoopTelemetry
from a2sdlc.lifecycle.comment import CommentManager
from a2sdlc.lifecycle.pr import PRLifecycle
from a2sdlc.pipeline import gating, ingress
from a2sdlc.pipeline.effects_apply import apply as apply_effects
from a2sdlc.pipeline.stage_finish import outcome_to_dispatch_tuple
from a2sdlc.stages import get_stage

# Transitional alias — P4 step 6. Dies in step 9.
DispatchContext = RunContext


async def dispatch(ctx: RunContext) -> DispatchResult:
    """Run one pipeline stage. Returns what happened."""
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

    ctx.pre = ctx.intent = intent
    ctx.pr_lifecycle = PRLifecycle(ctx.review)
    ctx.pr_number = _ensure_draft_pr(ctx, intent)
    ctx.stage_config = load_stage_config(intent.target_stage.value, ctx.config)
    _wire_comment_and_subscriber(ctx, intent)
    return await _run_attempted_stage(ctx, intent)


def _ensure_draft_pr(ctx: RunContext, intent: RunIntent) -> int | None:
    """Return the PR number, creating a draft on SPEC if none exists.

    GitHub rejects PRs against unpushed branches and empty-diff PRs —
    seed an empty commit, push, then open.
    """
    pr_number = intent.state.pr_number if intent.state else None
    if intent.target_stage == StageName.SPEC and pr_number is None:
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


async def _run_attempted_stage(ctx: RunContext, intent: RunIntent) -> DispatchResult:
    """Execute the resolved stage under telemetry + progress envelope.

    Emits ``stage_start`` / ``stage_end`` unconditionally once attempted.
    """
    stage_config = ctx.stage_config
    session_id = f"{intent.event.key}:{ctx.run_id or uuid.uuid4()}"
    telemetry = ctx.telemetry or NoopTelemetry()
    with (
        telemetry.session(session_id) as opener,
        opener.stage(intent.target_stage.value) as run,
    ):
        run.log_tag("ticket_key", intent.event.key)
        run.log_tag("target_stage", intent.target_stage.value)
        await ctx.progress_state.stage_start(
            intent.target_stage,
            session_id,
            model=stage_config.model,
            max_turns=stage_config.max_turns,
            context_window=context_window_for_model(stage_config.model) or 0,
            branch=intent.branch,
        )
        success: bool = False
        error: str | None = "unknown"
        try:
            ctx.run = run
            handler = get_stage(intent.target_stage)
            outcome = await handler.execute(ctx)
            await apply_effects(ctx, handler.effects(ctx, outcome))
            result, success, error = outcome_to_dispatch_tuple(intent, outcome)
            return result
        finally:
            await ctx.progress_state.stage_end(
                intent.target_stage,
                success=success,
                error=error,
                final=ctx.progress_state.snapshot_metrics(),
            )


__all__ = ["DispatchContext", "dispatch"]
