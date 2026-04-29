"""REVIEW stage — independent PR review."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from a2sdlc.assembly.prompt import assemble_system_prompt
from a2sdlc.config import StageConfig
from a2sdlc.domain.block_reason import BlockReason
from a2sdlc.domain.effects import (
    CommentFinalize,
    Effect,
    LogMetric,
    PostInlineReview,
    PostReview,
    SetCurrentStage,
    StateWrite,
)
from a2sdlc.domain.models import (
    StageName,
    StageStatus,
    TicketState,
    extract_inline_comments,
    strip_status_block,
)
from a2sdlc.domain.progress_format import format_final
from a2sdlc.domain.stage_outcome import StageOutcome
from a2sdlc.stages._shared import (
    agent_failure_outcome,
    commit_and_push_effect,
    no_status_block_outcome,
)

if TYPE_CHECKING:
    from a2sdlc.domain.run_context import RunContext


class ReviewStage:
    """REVIEW stage handler — P3 step 6 (effects migration).

    Keeps REVIEW-specific prompt assembly (PR context injection) and
    inline-comments parsing. Success-path side effects migrate to the
    effect list: PostReview + PostInlineReview replace the direct
    adapter calls. MergeStage-style: execute() is adapter-pure.
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

    def preconditions(self, ctx: "RunContext") -> BlockReason | None:
        return None

    def effects(self, ctx: "RunContext", outcome: StageOutcome) -> list[Effect]:
        return list(outcome.prepared_effects)

    async def execute(self, ctx: "RunContext") -> StageOutcome:
        pre = _require(ctx.intent, "intent")
        stage_config = _require(ctx.stage_config, "stage_config")
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

        # REVIEW user prompt — override wins, otherwise body (+ PR context
        # + issue Q&A discussion). read_context() is a PR-diff read;
        # collect_issue_feedback is the issue-comment fetch. Both are
        # read-only adapter calls and part of prompt assembly, not side
        # effects we migrate.
        if pre.user_prompt_override is not None:
            user_prompt = pre.user_prompt_override
        else:
            user_prompt = pre.clean_body
            if pr_number is not None:
                pr_context = pr_lifecycle.read_context(pr_number)
                user_prompt = f"{pre.clean_body}\n\n{pr_context}"
            discussion = _format_issue_discussion(
                ctx.work.collect_issue_feedback(pre.event.key, datetime.min)
            )
            if discussion:
                user_prompt = f"{user_prompt}\n\n{discussion}"

        executor = ctx.stage_executor
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

        # Failure path.
        if not exec_result.success:
            return agent_failure_outcome(
                pre, exec_result, stage_config, milestones, ctx_window
            )

        # No status block.
        if stage_result is None:
            return no_status_block_outcome(
                pre, exec_result, stage_config, milestones, ctx_window
            )

        # Success path.
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

        inline_comments = extract_inline_comments(exec_result.output, ctx.logger)

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

        effects: list[Effect] = [
            CommentFinalize(body=final_comment),
            StateWrite(state=new_state),
            commit_and_push_effect(),
        ]
        # Native PR review + inline comments (REVIEW-specific). Only when a
        # PR exists — matches the pre-migration conditional.
        if pr_number is not None:
            verdict = (
                "APPROVE"
                if stage_result.status == StageStatus.APPROVED
                else "REQUEST_CHANGES"
            )
            effects.append(
                PostReview(pr_number=pr_number, verdict=verdict, body=comment_body)
            )
            effects.append(
                PostInlineReview(pr_number=pr_number, comments=inline_comments)
            )
        # REVIEW.valid_statuses = {APPROVED, CHANGES_REQUESTED} — QUESTIONS
        # never surfaces, so no MarkNeedsInput branch here.
        if next_st is not None:
            effects.append(SetCurrentStage(stage=next_st))
        effects.extend(
            [
                LogMetric(key="tokens_in", value=float(exec_result.stats.tokens_in)),
                LogMetric(key="tokens_out", value=float(exec_result.stats.tokens_out)),
                LogMetric(key="cost_usd", value=float(exec_result.stats.cost_usd)),
                LogMetric(key="turns", value=float(exec_result.stats.num_turns)),
                LogMetric(
                    key="duration_ms", value=float(exec_result.stats.duration_ms)
                ),
            ]
        )

        return StageOutcome(
            status=stage_result.status,
            output_text=exec_result.output,
            stats=exec_result.stats,
            inline_comments=inline_comments,
            next_stage_hint=next_st,
            prepared_effects=effects,
        )


def _require(value, name):  # type: ignore[no-untyped-def]
    if value is None:
        msg = f"ReviewStage.execute requires ctx.{name} to be populated by dispatch"
        raise RuntimeError(msg)
    return value


def _format_issue_discussion(items: list) -> str:  # type: ignore[type-arg]
    """Render issue Q&A comments for the REVIEW user prompt.

    Distinct from ``_format_feedback_section`` in ``ingress/context.py``
    (which frames feedback as TODO items the agent must address). REVIEW
    only needs the conversation that shaped the spec for context — no
    "address this" framing.
    """
    if not items:
        return ""
    lines = ["## Issue Discussion (for context)\n"]
    for item in sorted(items, key=lambda f: f.created_at):
        lines.append(f"### {item.source} by @{item.author}")
        lines.append(item.body)
        lines.append("")
    return "\n".join(lines)
