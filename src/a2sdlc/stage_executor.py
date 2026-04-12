"""StageExecutor — runs a stage via the runner, handles follow-up prompts, accumulates stats."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from a2sdlc.adapters.protocols import StageRunner
from a2sdlc.config import StageConfig
from a2sdlc.models import StageName, StageResult, extract_result
from a2sdlc.progress import ProgressState
from a2sdlc.stats import StageRunStats

_FOLLOWUP_PROMPT = (
    "Work phase complete. Provide your structured handover now. "
    "Respond with ONLY a ```a2sdlc block containing: "
    '{{"status": "...", "ticket_summary": "..."}}. '
    "Valid statuses: complete, questions, approved, changes_requested."
)

_MAX_FOLLOWUP_ATTEMPTS = 3


@dataclass
class ExecutionResult:
    """Result of a full stage execution, including any follow-up rounds."""

    output: str
    stage_result: StageResult | None
    stats: StageRunStats
    success: bool
    error: str | None = None
    milestones: list[Any] = field(default_factory=list)
    progress: ProgressState | None = None


class StageExecutor:
    """Runs a stage and handles structured-output follow-up prompts."""

    def __init__(self, runner: StageRunner) -> None:
        self._runner = runner

    async def run(
        self,
        user_prompt: str,
        system_prompt: str,
        config: StageConfig,
        ticket_key: str,
        stage: StageName,
        project_root: str,
        is_resume: bool = False,
        on_progress: Callable[[str], None] | None = None,
        branch: str = "",
    ) -> ExecutionResult:
        stats = StageRunStats()
        combined_output = ""

        # ── Initial run ───────────────────────────────────────────────
        result = await self._runner.run(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            config=config,
            ticket_key=ticket_key,
            stage=stage,
            project_root=project_root,
            is_resume=is_resume,
            on_progress=on_progress,
            branch=branch,
        )
        stats.add_from_result(result)
        combined_output += result.output

        if not result.success:
            return ExecutionResult(
                output=combined_output,
                stage_result=None,
                stats=stats,
                success=False,
                error=result.error,
                milestones=_milestones(result),
                progress=result.progress,
            )

        stage_result = extract_result(result.output)
        if stage_result is not None:
            return ExecutionResult(
                output=combined_output,
                stage_result=stage_result,
                stats=stats,
                success=True,
                milestones=_milestones(result),
                progress=result.progress,
            )

        # ── Follow-up attempts ────────────────────────────────────────
        last_result = result
        for _ in range(_MAX_FOLLOWUP_ATTEMPTS):
            followup = await self._runner.run(
                user_prompt=_FOLLOWUP_PROMPT,
                system_prompt=system_prompt,
                config=config,
                ticket_key=ticket_key,
                stage=stage,
                project_root=project_root,
                is_resume=True,
                on_progress=on_progress,
                branch=branch,
            )
            stats.add_from_result(followup)
            combined_output += "\n" + followup.output
            last_result = followup

            stage_result = extract_result(followup.output)
            if stage_result is not None:
                return ExecutionResult(
                    output=combined_output,
                    stage_result=stage_result,
                    stats=stats,
                    success=True,
                    milestones=_milestones(last_result),
                    progress=last_result.progress,
                )

        # All follow-ups exhausted
        return ExecutionResult(
            output=combined_output,
            stage_result=None,
            stats=stats,
            success=True,
            milestones=_milestones(last_result),
            progress=last_result.progress,
        )


def _milestones(result: object) -> list[Any]:
    """Extract milestones from a RunResult's progress state."""
    progress = getattr(result, "progress", None)
    if progress is None:
        return []
    return list(getattr(progress, "milestones", []))
