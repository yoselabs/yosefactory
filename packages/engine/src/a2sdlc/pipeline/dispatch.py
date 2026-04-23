"""Dispatch — composition root for one pipeline run.

Thin orchestrator: preflight → ensure draft PR → comment + subscriber →
telemetry session → delegate to the per-stage handler. Each AI stage
owns its own ``execute()``; MERGE too since P2 step 8. This file wires
them together and owns the StageEnd emission contract (fires
unconditionally once a stage is attempted).
"""

from __future__ import annotations

import uuid

from a2sdlc.config import load_stage_config
from a2sdlc.domain.effects import AwaitHumanDecision, Effect, MarkBlocked
from a2sdlc.domain.models import StageName
from a2sdlc.domain.progress_format import context_window_for_model
from a2sdlc.domain.run_context import RunContext
from a2sdlc.domain.run_result import DispatchResult
from a2sdlc.domain.stage_outcome import StageOutcome
from a2sdlc.evaluation.telemetry import NoopTelemetry, Telemetry
from a2sdlc.lifecycle.comment import CommentManager
from a2sdlc.lifecycle.pr import PRLifecycle
from a2sdlc.pipeline import gating, ingress
from a2sdlc.pipeline.effects_apply import apply as apply_effects
from a2sdlc.pipeline.preflight import PreflightOutcome
from a2sdlc.stages import get_stage

# Transitional alias — P4 step 6. ``DispatchContext`` was renamed +
# relocated to ``domain.run_context.RunContext``; the alias avoids a
# big-bang rename of every test file. Dies in step 9.
DispatchContext = RunContext


async def dispatch(ctx: DispatchContext) -> DispatchResult:
    """Run one pipeline stage. Returns what happened."""
    # 1. Ingress + gating + intent resolution — explicit composition
    # root shape per architecture vision §7.3. Early returns cover
    # skip / closed / inactive / duplicate / tripped-breaker /
    # git-blocked.
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

    pre = ingress.resolve_intent(ctx, event)
    if isinstance(pre, DispatchResult):
        return pre

    # 2. Draft PR creation (on spec stage if no PR exists yet).
    pr_lifecycle = PRLifecycle(ctx.review)
    pr_number = _ensure_draft_pr(ctx, pre, pr_lifecycle)

    # 3. Start comment + comment-driving subscriber. Dispatch doesn't
    # know which subscriber class — the CLI supplies a factory.
    comment = CommentManager(ctx.work, pre.event.key)
    comment.start(pre.target_stage.value)
    if ctx.make_comment_subscriber is not None:
        ctx.progress_state.subscribe(ctx.make_comment_subscriber(comment))

    # 4. Load stage config early so stage_start has model/max_turns even for MERGE.
    stage_config = load_stage_config(pre.target_stage.value, ctx.config)
    # Scope MLflow parent per-run so A/B fan-outs on one ticket don't collide.
    session_id = f"{pre.event.key}:{ctx.run_id or uuid.uuid4()}"
    # Telemetry wraps only actually-attempted stages. Pre-execution early
    # returns intentionally produce no MLflow runs.
    telemetry = ctx.telemetry or NoopTelemetry()

    # Populate per-run orchestration state on ctx so handlers can read it
    # via a single argument. ``ctx.pre`` stays for legacy reads; ``ctx.intent``
    # is the renamed alias pointing at the same RunIntent value (P4 step 7).
    ctx.pre = pre
    ctx.intent = pre
    ctx.pr_lifecycle = pr_lifecycle
    ctx.comment = comment
    ctx.pr_number = pr_number
    ctx.stage_config = stage_config

    return await _run_attempted_stage(
        ctx,
        pre,
        pr_lifecycle,
        comment,
        pr_number,
        stage_config,
        session_id,
        telemetry,
    )


def _ensure_draft_pr(
    ctx: DispatchContext,
    pre: PreflightOutcome,
    pr_lifecycle: PRLifecycle,
) -> int | None:
    """Return the PR number for this ticket, creating a draft on SPEC if needed.

    GitHub rejects PRs against unpushed branches and empty-diff PRs —
    seed an empty commit, push, then open.
    """
    pr_number = pre.state.pr_number if pre.state else None
    if pre.target_stage == StageName.SPEC and pr_number is None:
        ctx.git.commit_empty(f"chore(a2sdlc): open session for {pre.event.key}")
        ctx.git.push()
        pr_number = pr_lifecycle.create_draft(pre.branch, pre.base, pre.event.key)
        ctx.logger.info("dispatch.draft_pr_created", extra={"pr": pr_number})

    if pre.event.pr_number is not None:
        pr_number = pre.event.pr_number

    return pr_number


async def _run_attempted_stage(
    ctx: DispatchContext,
    pre: PreflightOutcome,
    pr_lifecycle: PRLifecycle,
    comment: CommentManager,
    pr_number: int | None,
    stage_config,  # noqa: ANN001 — forward ref to StageConfig
    session_id: str,
    telemetry: Telemetry,
) -> DispatchResult:
    """Execute a stage under telemetry + progress envelope.

    Emits `stage_start` / `stage_end` unconditionally once the stage is
    attempted. Resolves the handler via the ``STAGES`` registry and awaits
    its ``execute()``.
    """
    with (
        telemetry.session(session_id) as opener,
        opener.stage(pre.target_stage.value) as run,
    ):
        run.log_tag("ticket_key", pre.event.key)
        run.log_tag("target_stage", pre.target_stage.value)

        await ctx.progress_state.stage_start(
            pre.target_stage,
            session_id,
            model=stage_config.model,
            max_turns=stage_config.max_turns,
            context_window=context_window_for_model(stage_config.model) or 0,
            branch=pre.branch,
        )

        # Default error to "unknown" so an unhandled crash produces an
        # informative StageEnd payload.
        success: bool = False
        error: str | None = "unknown"

        try:
            ctx.run = run
            handler = get_stage(pre.target_stage)
            outcome = await handler.execute(ctx)
            # P3 step 3: handlers return ``effects()==[]`` today — the
            # call is a no-op seam. Per-handler migration in steps 4–7
            # populates these lists; the interpreter handles them
            # uniformly in list order.
            await apply_effects(ctx, handler.effects(ctx, outcome))
            result, success, error = _outcome_to_dispatch_tuple(pre, outcome)
            return result

        finally:
            await ctx.progress_state.stage_end(
                pre.target_stage,
                success=success,
                error=error,
                final=ctx.progress_state.snapshot_metrics(),
            )


_PAUSE_ARMS = (MarkBlocked, AwaitHumanDecision)


def _pipeline_pause_reason(effects: list[Effect]) -> str | None:
    """Return the pause-reason label if the effect list signals a non-advance.

    Two arms signal "this run did not advance the pipeline":
    - ``MarkBlocked`` — platform-visible ticket flag (failure paths).
    - ``AwaitHumanDecision`` — pipeline-pause signal with no platform
      flag (human-gate waits).

    Either presence means dispatch should emit a ``success=False``
    ``stage_end`` telemetry event and expose the reason as the error
    label. Returns ``None`` when the run advanced (or merged).
    """
    for eff in effects:
        if isinstance(eff, _PAUSE_ARMS):
            return eff.reason
    return None


def _outcome_to_dispatch_tuple(
    pre: PreflightOutcome, outcome: StageOutcome
) -> tuple[DispatchResult, bool, str | None]:
    """Translate a handler's StageOutcome into dispatch's tuple shape.

    The ``(DispatchResult, success, error)`` shape feeds ``stage_end``
    telemetry. Pause signal flows from the effect list (see
    ``_pipeline_pause_reason``); status/merged/next_stage_hint stay on
    the outcome. P4 collapses this translator entirely when
    ``RunContext`` lands.
    """
    pause_reason = _pipeline_pause_reason(outcome.prepared_effects)
    if pause_reason is not None:
        return (
            DispatchResult(
                stage=pre.target_stage,
                blocked=True,
                error=pause_reason,
                output=outcome.output_text,
            ),
            False,
            pause_reason,
        )
    # MERGE happy path — deterministic, no StageStatus. The ``merged`` flag
    # is the success discriminator; dispatch emits a status-less result.
    if outcome.merged:
        return (
            DispatchResult(stage=pre.target_stage),
            True,
            None,
        )
    # AI-stage happy path — status is present.
    assert outcome.status is not None, "non-paused StageOutcome must carry a status"  # noqa: S101
    return (
        DispatchResult(
            stage=pre.target_stage,
            status=outcome.status,
            next_stage=outcome.next_stage_hint,
            blocked=False,
            stats=outcome.stats,
            output=outcome.output_text,
        ),
        True,
        None,
    )


__all__ = ["DispatchContext", "dispatch"]
