"""Shared helpers for AI stage handlers — P3 step 8.

SpecStage / ImplementStage / ReviewStage share two identical error-path
shapes (agent-execution failure, missing-status-block) that each emit a
``CommentFinalize + CommitAndPush + MarkBlocked`` triple. Before step 8
each handler carried its own ~60 LOC of copy-pasted glue; now each
handler calls one of the helpers below and returns the result.

MergeStage's blocked paths are different-shaped (no CommitAndPush, no
format_error) so they don't share these helpers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from a2sdlc.domain.effects import (
    CommentFinalize,
    CommitAndPush,
    Effect,
    MarkBlocked,
)
from a2sdlc.domain.progress_format import format_error, format_final
from a2sdlc.domain.stage_outcome import StageOutcome

if TYPE_CHECKING:
    from a2sdlc.config import StageConfig
    from a2sdlc.pipeline.preflight import PreflightOutcome
    from a2sdlc.pipeline.stage_executor import ExecutionResult

COMMIT_MESSAGE = "chore: stage artifacts"
ARTIFACT_PATHS = (".a2sdlc/state/state.json", "docs/")


def commit_and_push_effect() -> CommitAndPush:
    """Canonical post-stage commit — all three AI handlers share this."""
    return CommitAndPush(message=COMMIT_MESSAGE, paths=ARTIFACT_PATHS)


def agent_failure_outcome(
    pre: "PreflightOutcome",
    exec_result: "ExecutionResult",
    stage_config: "StageConfig",
    milestones,  # type: ignore[no-untyped-def]
    ctx_window: int | None,
) -> StageOutcome:
    """Build the blocked outcome + effect list for an agent-execution failure."""
    error = exec_result.error or "unknown"
    error_comment = format_error(
        error,
        stage=pre.target_stage.value,
        stats=exec_result.stats,
        milestones=milestones,
        model=stage_config.model,
        branch=pre.branch,
        max_turns=stage_config.max_turns,
        context_window=ctx_window,
    )
    effects: list[Effect] = [
        CommentFinalize(body=error_comment),
        commit_and_push_effect(),
        MarkBlocked(reason=error),
    ]
    return StageOutcome(
        output_text=exec_result.output,
        stats=exec_result.stats,
        blocked=True,
        error=error,
        prepared_effects=effects,
    )


def no_status_block_outcome(
    pre: "PreflightOutcome",
    exec_result: "ExecutionResult",
    stage_config: "StageConfig",
    milestones,  # type: ignore[no-untyped-def]
    ctx_window: int | None,
) -> StageOutcome:
    """Build the blocked outcome + effects when the agent returned no status block."""
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
    effects: list[Effect] = [
        CommentFinalize(body=error_msg),
        commit_and_push_effect(),
        MarkBlocked(reason="no status block in output"),
    ]
    return StageOutcome(
        output_text=exec_result.output,
        stats=exec_result.stats,
        blocked=True,
        error="no_status_block",
        prepared_effects=effects,
    )


__all__ = [
    "COMMIT_MESSAGE",
    "ARTIFACT_PATHS",
    "commit_and_push_effect",
    "agent_failure_outcome",
    "no_status_block_outcome",
]
