"""IMPLEMENT stage — autonomous code implementation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from a2sdlc.assembly.prompt import assemble_system_prompt
from a2sdlc.config import StageConfig
from a2sdlc.domain.block_reason import BlockReason
from a2sdlc.domain.effects import (
    AwaitHumanDecision,
    CommentFinalize,
    Effect,
    LogMetric,
    MarkNeedsInput,
    SetCurrentStage,
    StateWrite,
)
from a2sdlc.domain.models import (
    StageName,
    StageStatus,
    TicketState,
    strip_status_block,
)
from a2sdlc.domain.progress_format import format_final
from a2sdlc.domain.stage_outcome import StageOutcome
from a2sdlc.pipeline.stage_executor import StageExecutor
from a2sdlc.stages._shared import (
    agent_failure_outcome,
    commit_and_push_effect,
    no_status_block_outcome,
)

if TYPE_CHECKING:
    from a2sdlc.domain.run_context import RunContext

_DEFAULT_TOOLS = [
    "Bash",
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "Agent",
    "Skill",
]


class ImplementStage:
    """IMPLEMENT stage handler — P3 step 5 (effects migration).

    Mirrors SpecStage's effect-migration shape. Difference from SPEC: no
    self-answer prefix; CHANGES_REQUESTED status is impossible (not in
    valid_statuses) so review_cycles is carried unchanged on success.
    """

    name = StageName.IMPLEMENT
    uses_ai = True
    valid_statuses = frozenset({StageStatus.COMPLETE, StageStatus.QUESTIONS})
    config = StageConfig(
        name="implement",
        max_turns=150,
        timeout_minutes=60,
        allowed_tools=list(_DEFAULT_TOOLS),
    )

    def preconditions(self, ctx: "RunContext") -> BlockReason | None:
        return None

    def effects(self, ctx: "RunContext", outcome: StageOutcome) -> list[Effect]:
        return list(outcome.prepared_effects)

    async def execute(self, ctx: "RunContext") -> StageOutcome:
        pre = _require(ctx.intent, "intent")
        stage_config = _require(ctx.stage_config, "stage_config")

        system_prompt = assemble_system_prompt(
            pre.target_stage.value, ctx.project_root / ".a2sdlc"
        )
        if pre.event.is_feedback:
            system_prompt = (
                "IMPORTANT: You are addressing feedback on your previous work. "
                "Focus on the feedback items below.\n\n" + system_prompt
            )

        user_prompt = (
            pre.user_prompt_override
            if pre.user_prompt_override is not None
            else pre.clean_body
        )

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

        # IMPLEMENT.valid_statuses = {COMPLETE, QUESTIONS} — review_cycles unchanged.
        review_cycles = pre.state.review_cycles if pre.state else 0
        new_state = TicketState(
            stage=pre.target_stage,
            status=stage_result.status,
            base_branch=pre.base,
            branch=pre.branch,
            pr_number=ctx.pr_number,
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
        if next_st is not None:
            effects.append(SetCurrentStage(stage=next_st))
        elif stage_result.status == StageStatus.QUESTIONS:
            effects.append(MarkNeedsInput())
            effects.append(AwaitHumanDecision(kind="input", reason="questions"))
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
            next_stage_hint=next_st,
            prepared_effects=effects,
        )


def _require(value, name):  # type: ignore[no-untyped-def]
    if value is None:
        msg = f"ImplementStage.execute requires ctx.{name} to be populated by dispatch"
        raise RuntimeError(msg)
    return value
