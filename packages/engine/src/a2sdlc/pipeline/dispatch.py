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
from a2sdlc.lifecycle.comment import CommentManager
from a2sdlc.lifecycle.pr import PRLifecycle
from a2sdlc import ingress
from a2sdlc import gating
from a2sdlc.effects.apply import apply as apply_effects
from a2sdlc.middleware.idempotency import with_idempotency
from a2sdlc.middleware.telemetry import with_telemetry
from a2sdlc.effects.stage_finish import outcome_to_dispatch_result
from a2sdlc.stages import get_stage


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

    ctx.intent = intent
    ctx.pr_lifecycle = PRLifecycle(ctx.review)
    ctx.pr_number = _ensure_draft_pr(ctx, intent)
    ctx.stage_config = load_stage_config(intent.target_stage.value, ctx.config)
    _wire_comment_and_subscriber(ctx, intent)

    stack = with_idempotency(with_telemetry(run_stage))
    return await stack(ctx, intent)


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
