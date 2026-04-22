"""AI stage execution — SPEC, IMPLEMENT, REVIEW.

Called from `dispatch.py` inside the telemetry session context. Builds
prompts, runs the `StageExecutor`, handles three result shapes (failure,
missing-status-block, success), persists state, and transitions labels.

Returns `(result, success, error)` so the caller can emit `stage_end`
without re-deriving success/error from the DispatchResult.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from a2sdlc.assembly.prompt import assemble_system_prompt
from a2sdlc.domain.models import (
    StageName,
    StageStatus,
    TicketState,
    strip_status_block,
)
from a2sdlc.domain.progress_format import format_error, format_final
from a2sdlc.domain.run_result import DispatchResult
from a2sdlc.pipeline.stage_executor import StageExecutor
from a2sdlc.stages import next_stage

if TYPE_CHECKING:
    from a2sdlc.config import StageConfig
    from a2sdlc.evaluation.telemetry import RunHandle
    from a2sdlc.lifecycle.comment import CommentManager
    from a2sdlc.lifecycle.pr import PRLifecycle
    from a2sdlc.pipeline.dispatch import DispatchContext
    from a2sdlc.pipeline.preflight import PreflightOutcome


async def execute_ai_stage(
    ctx: "DispatchContext",
    pre: "PreflightOutcome",
    pr_lifecycle: "PRLifecycle",
    comment: "CommentManager",
    pr_number: int | None,
    stage_config: "StageConfig",
    run: "RunHandle",
) -> tuple[DispatchResult, bool, str | None]:
    """Run SPEC/IMPLEMENT/REVIEW end-to-end.

    On failure or missing-status-block: commit+push, mark_blocked, early
    return. On success: strip status, finalize comment, optionally post
    review, write state, transition labels, log metrics.
    """
    # 1. Assemble prompts.
    system_prompt = assemble_system_prompt(
        pre.target_stage.value, ctx.project_root / ".a2sdlc"
    )

    if pre.event.is_feedback:
        system_prompt = (
            "IMPORTANT: You are addressing feedback on your previous work. "
            "Focus on the feedback items below.\n\n" + system_prompt
        )

    if pre.self_answer and pre.target_stage == StageName.SPEC:
        system_prompt = (
            "IMPORTANT: Make your best judgment for all ambiguous requirements. "
            "Do not ask questions — produce the spec directly.\n\n" + system_prompt
        )

    # 2. User prompt — override from feedback routing, else body (+PR context on REVIEW).
    if pre.user_prompt_override is not None:
        user_prompt = pre.user_prompt_override
    else:
        user_prompt = pre.clean_body
        if pre.target_stage == StageName.REVIEW and pr_number is not None:
            pr_context = pr_lifecycle.read_context(pr_number)
            user_prompt = f"{pre.clean_body}\n\n{pr_context}"

    # 3. Execute stage.
    executor = StageExecutor(ctx.runner)
    exec_result = await executor.run(
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        config=stage_config,
        ticket_key=pre.event.key,
        stage=pre.target_stage,
        project_root=str(ctx.project_root),
        progress_state=ctx.progress_state,
        is_resume=False,
        branch=pre.branch,
    )

    stage_result = exec_result.stage_result

    # 4. Log full output to CI.
    ctx.logger.info("agent.output", extra={"len": len(exec_result.output)})

    milestones = exec_result.milestones
    ctx_window = exec_result.progress.context_window if exec_result.progress else None

    def _commit_and_push() -> None:
        # Commit the state.json ledger + real deliverables (docs/). Other
        # runtime under .a2sdlc/state/ (logs) stays on the runner's tree
        # and is never committed. Pre-merge strip wipes the whole
        # .a2sdlc/state/ folder before the squash.
        try:
            ctx.git.commit_artifacts(
                "chore: stage artifacts",
                [".a2sdlc/state/state.json", "docs/"],
            )
            ctx.git.push()
        except Exception:  # noqa: BLE001
            ctx.logger.warning("dispatch.commit_push_failed", exc_info=True)

    # 5. Failure path.
    if not exec_result.success:
        error_comment = format_error(
            exec_result.error or "unknown",
            stage=pre.target_stage.value,
            stats=exec_result.stats,
            milestones=milestones,
            model=stage_config.model,
            branch=pre.branch,
            max_turns=stage_config.max_turns,
            context_window=ctx_window,
        )
        comment.finalize(error_comment)
        _commit_and_push()
        ctx.work.mark_blocked(pre.event.key, exec_result.error or "unknown")
        err = exec_result.error or "unknown"
        return (
            DispatchResult(
                stage=pre.target_stage,
                blocked=True,
                error=exec_result.error,
                output=exec_result.output,
            ),
            False,
            err,
        )

    # 6. No status block even after follow-ups.
    if stage_result is None:
        partial = exec_result.output[:2000]
        no_status_footer = format_final(
            partial,
            stage=pre.target_stage.value,
            stats=exec_result.stats,
            milestones=milestones,
            model=stage_config.model,
            branch=pre.branch,
            max_turns=stage_config.max_turns,
            context_window=ctx_window,
        )
        error_msg = (
            f"⚠️ No status block in **{pre.target_stage.value}** output."
            f"\n\n{partial}\n\n{no_status_footer}"
        )
        comment.finalize(error_msg)
        _commit_and_push()
        ctx.work.mark_blocked(pre.event.key, "no status block in output")
        return (
            DispatchResult(
                stage=pre.target_stage,
                blocked=True,
                error="no_status_block",
                output=exec_result.output,
            ),
            False,
            "no_status_block",
        )

    # 7. Success path.
    comment_body = strip_status_block(exec_result.output)
    tasks = exec_result.progress.tasks if exec_result.progress else None
    final_comment = format_final(
        comment_body,
        stage=pre.target_stage.value,
        stats=exec_result.stats,
        milestones=milestones,
        model=stage_config.model,
        branch=pre.branch,
        max_turns=stage_config.max_turns,
        context_window=ctx_window,
        tasks=tasks,
    )
    comment.finalize(final_comment)

    # Side effects — post PR review on REVIEW stage.
    if pre.target_stage == StageName.REVIEW and pr_number is not None:
        verdict = (
            "APPROVE"
            if stage_result.status == StageStatus.APPROVED
            else "REQUEST_CHANGES"
        )
        pr_lifecycle.post_review(pr_number, comment_body, verdict)

    # 8. Write state.
    review_cycles = pre.state.review_cycles if pre.state else 0
    if stage_result.status == StageStatus.CHANGES_REQUESTED:
        review_cycles += 1
    new_state = TicketState(
        stage=pre.target_stage,
        status=stage_result.status,
        base_branch=pre.base,
        branch=pre.branch,
        pr_number=pr_number,
        stage_run_id=ctx.run_id or "",
        review_cycles=review_cycles,
        accumulated_cost_usd=(pre.state.accumulated_cost_usd if pre.state else 0.0)
        + exec_result.stats.cost_usd,
        accumulated_tokens_in=(pre.state.accumulated_tokens_in if pre.state else 0)
        + exec_result.stats.tokens_in,
        accumulated_tokens_out=(pre.state.accumulated_tokens_out if pre.state else 0)
        + exec_result.stats.tokens_out,
        accumulated_duration_ms=(pre.state.accumulated_duration_ms if pre.state else 0)
        + exec_result.stats.duration_ms,
        last_updated=datetime.now(timezone.utc).isoformat(),
    )
    pre.state_mgr.write_state(new_state)
    _commit_and_push()

    # 9. Transition labels.
    next_st = next_stage(pre.target_stage, stage_result.status, pre.gates)

    ctx.logger.info(
        "dispatch.transition",
        extra={
            "from": pre.target_stage.value,
            "status": stage_result.status.value,
            "to": next_st.value if next_st else None,
        },
    )

    if next_st is not None:
        ctx.work.set_current_stage(pre.event.key, next_st)
    elif stage_result.status == StageStatus.QUESTIONS:
        ctx.work.mark_needs_input(pre.event.key)  # pipeline paused on human reply

    # 10. Metrics (logged before the telemetry context manager exits).
    run.log_metric("tokens_in", exec_result.stats.tokens_in)
    run.log_metric("tokens_out", exec_result.stats.tokens_out)
    run.log_metric("cost_usd", exec_result.stats.cost_usd)
    run.log_metric("turns", exec_result.stats.num_turns)
    run.log_metric("duration_ms", exec_result.stats.duration_ms)

    return (
        DispatchResult(
            stage=pre.target_stage,
            status=stage_result.status,
            next_stage=next_st,
            blocked=False,
            stats=exec_result.stats,
            output=exec_result.output,
        ),
        True,
        None,
    )


__all__ = ["execute_ai_stage"]
