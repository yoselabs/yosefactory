"""REVIEW stage — independent PR review."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from a2sdlc.assembly.prompt import assemble_system_prompt
from a2sdlc.config import StageConfig
from a2sdlc.domain.block_reason import BlockReason
from a2sdlc.domain.effects import Effect
from a2sdlc.domain.models import (
    StageName,
    StageStatus,
    TicketState,
    extract_inline_comments,
    strip_status_block,
)
from a2sdlc.domain.progress_format import format_error, format_final
from a2sdlc.domain.stage_outcome import StageOutcome
from a2sdlc.pipeline.stage_executor import StageExecutor

if TYPE_CHECKING:
    from a2sdlc.pipeline.dispatch import DispatchContext


class ReviewStage:
    """REVIEW stage handler — P2 step 6.

    Mirrors SpecStage's structure with two REVIEW-specific additions:

    1. PR context injection — when a PR number is known, the user prompt
       gets the diff + existing comments appended (via ``PRLifecycle``).
    2. Native PR review posting — on success, ``post_review`` is called
       with APPROVE / REQUEST_CHANGES, and ``post_inline_comments`` is
       invoked (unconditionally — empty list is a no-op per the adapter
       Protocol). The ``outcome.inline_comments`` parser itself lands in
       step 7; step 6 just threads an empty list through.
    """

    name = StageName.REVIEW
    uses_ai = True
    valid_statuses = frozenset({StageStatus.APPROVED, StageStatus.CHANGES_REQUESTED})
    config = StageConfig(
        name="review",
        max_turns=150,
        timeout_minutes=20,
        allowed_tools=[
            "Bash",
            "Read",
            "Glob",
            "Grep",
            "WebFetch",
            "WebSearch",
            "Agent",
            "Skill",
        ],
    )

    def preconditions(self, ctx: "DispatchContext") -> BlockReason | None:
        return None

    def effects(self, ctx: "DispatchContext", outcome: StageOutcome) -> list[Effect]:
        return []

    async def execute(self, ctx: "DispatchContext") -> StageOutcome:
        pre = _require(ctx.pre, "pre")
        comment = _require(ctx.comment, "comment")
        stage_config = _require(ctx.stage_config, "stage_config")
        run = _require(ctx.run, "run")
        pr_lifecycle = _require(ctx.pr_lifecycle, "pr_lifecycle")
        pr_number = ctx.pr_number

        system_prompt = assemble_system_prompt(
            pre.target_stage.value, ctx.project_root / ".a2sdlc"
        )
        if pre.event.is_feedback:
            system_prompt = (
                "IMPORTANT: You are addressing feedback on your previous work. "
                "Focus on the feedback items below.\n\n" + system_prompt
            )

        # REVIEW user prompt — override wins, otherwise body (+ PR context).
        if pre.user_prompt_override is not None:
            user_prompt = pre.user_prompt_override
        else:
            user_prompt = pre.clean_body
            if pr_number is not None:
                pr_context = pr_lifecycle.read_context(pr_number)
                user_prompt = f"{pre.clean_body}\n\n{pr_context}"

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
        ctx.logger.info("agent.output", extra={"len": len(exec_result.output)})
        milestones = exec_result.milestones
        ctx_window = (
            exec_result.progress.context_window if exec_result.progress else None
        )

        def _commit_and_push() -> None:
            try:
                ctx.git.commit_artifacts(
                    "chore: stage artifacts",
                    [".a2sdlc/state/state.json", "docs/"],
                )
                ctx.git.push()
            except Exception:  # noqa: BLE001
                ctx.logger.warning("dispatch.commit_push_failed", exc_info=True)

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
            return StageOutcome(
                output_text=exec_result.output,
                stats=exec_result.stats,
                blocked=True,
                error=exec_result.error or "unknown",
            )

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
            return StageOutcome(
                output_text=exec_result.output,
                stats=exec_result.stats,
                blocked=True,
                error="no_status_block",
            )

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
            status=stage_result.status.value,
        )
        comment.finalize(final_comment)

        # REVIEW side effects — native PR review + inline comments.
        inline_comments = extract_inline_comments(exec_result.output, ctx.logger)
        if pr_number is not None:
            verdict = (
                "APPROVE"
                if stage_result.status == StageStatus.APPROVED
                else "REQUEST_CHANGES"
            )
            pr_lifecycle.post_review(pr_number, comment_body, verdict)
            ctx.review.post_inline_comments(pr_number, inline_comments)

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
            accumulated_tokens_out=(
                pre.state.accumulated_tokens_out if pre.state else 0
            )
            + exec_result.stats.tokens_out,
            accumulated_duration_ms=(
                pre.state.accumulated_duration_ms if pre.state else 0
            )
            + exec_result.stats.duration_ms,
            last_updated=datetime.now(timezone.utc).isoformat(),
        )
        pre.state_mgr.write_state(new_state)
        _commit_and_push()

        from a2sdlc.stages import next_stage  # local import to avoid cycle

        next_st = next_stage(pre.target_stage, stage_result.status, pre.gates)
        ctx.logger.info(
            "dispatch.transition",
            extra={
                "from": pre.target_stage.value,
                "status": stage_result.status.value,
                "to": next_st.value if next_st else None,
            },
        )
        # REVIEW.valid_statuses = {APPROVED, CHANGES_REQUESTED} — QUESTIONS
        # never surfaces, so there is no mark_needs_input path here.
        if next_st is not None:
            ctx.work.set_current_stage(pre.event.key, next_st)

        run.log_metric("tokens_in", exec_result.stats.tokens_in)
        run.log_metric("tokens_out", exec_result.stats.tokens_out)
        run.log_metric("cost_usd", exec_result.stats.cost_usd)
        run.log_metric("turns", exec_result.stats.num_turns)
        run.log_metric("duration_ms", exec_result.stats.duration_ms)

        return StageOutcome(
            status=stage_result.status,
            output_text=exec_result.output,
            stats=exec_result.stats,
            inline_comments=inline_comments,
            next_stage_hint=next_st,
        )


def _require(value, name):  # type: ignore[no-untyped-def]
    if value is None:
        msg = f"ReviewStage.execute requires ctx.{name} to be populated by dispatch"
        raise RuntimeError(msg)
    return value
