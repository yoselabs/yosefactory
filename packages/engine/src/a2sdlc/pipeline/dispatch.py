"""Dispatch — composition root for one pipeline run.

Thin orchestrator: preflight → ensure draft PR → comment + subscriber →
telemetry session → delegate to merge_flow or stage_run. Each phase
lives in its own module (see `preflight.py`, `merge_flow.py`,
`stage_run.py`). This file wires them together and owns the StageEnd
emission contract (fires unconditionally once a stage is attempted).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from a2sdlc.adapters.git import GitAdapter
from a2sdlc.adapters.review import ReviewAdapter
from a2sdlc.adapters.runner import StageRunner
from a2sdlc.adapters.work import WorkAdapter
from a2sdlc.config import ProjectConfig, load_stage_config
from a2sdlc.domain.models import StageName
from a2sdlc.domain.progress import ProgressState, Subscriber
from a2sdlc.domain.progress_format import context_window_for_model
from a2sdlc.domain.run_result import DispatchResult
from a2sdlc.evaluation.telemetry import NoopTelemetry, Telemetry
from a2sdlc.lifecycle.comment import CommentManager
from a2sdlc.lifecycle.pr import PRLifecycle
from a2sdlc.pipeline.merge_flow import execute_merge
from a2sdlc.pipeline.preflight import PreflightOutcome, run_preflight
from a2sdlc.pipeline.stage_run import execute_ai_stage


@dataclass
class DispatchContext:
    """All external dependencies — injected, not constructed."""

    work: WorkAdapter
    git: GitAdapter
    review: ReviewAdapter
    runner: StageRunner
    progress_state: ProgressState
    config: ProjectConfig
    project_root: Path
    logger: logging.Logger
    run_id: str | None = None
    make_comment_subscriber: Callable[[CommentManager], Subscriber] | None = None
    telemetry: "Telemetry | None" = (
        None  # optional for back-compat; CLI always supplies
    )


async def dispatch(ctx: DispatchContext) -> DispatchResult:
    """Run one pipeline stage. Returns what happened."""
    # 1. Preflight — event parse, routing, branch setup, idempotency,
    # circuit breakers. Early-returns for skip/closed/inactive/duplicate/
    # tripped-breaker/git-blocked.
    pre = run_preflight(ctx)
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
    attempted. Delegates to `execute_merge` for deterministic MERGE or
    `execute_ai_stage` for SPEC/IMPLEMENT/REVIEW.
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
            if pre.target_stage == StageName.MERGE:
                result, success, error = execute_merge(
                    ctx, pre, pr_lifecycle, comment, pr_number
                )
                return result

            result, success, error = await execute_ai_stage(
                ctx, pre, pr_lifecycle, comment, pr_number, stage_config, run
            )
            return result

        finally:
            await ctx.progress_state.stage_end(
                pre.target_stage,
                success=success,
                error=error,
                final=ctx.progress_state.snapshot_metrics(),
            )


__all__ = ["DispatchContext", "dispatch"]
