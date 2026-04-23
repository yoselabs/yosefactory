"""Stage execution result type.

Lives in ``domain/`` so stage handlers can type against the result
shape without importing from ``pipeline/`` — the ``StageExecutor``
class itself stays in ``pipeline/`` (it needs adapter + config
imports). Stage handlers receive a pre-built executor via
``RunContext.stage_executor`` and only need the return-type shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from a2sdlc.domain.stats import StageRunStats

if TYPE_CHECKING:
    from a2sdlc.domain.models import StageResult
    from a2sdlc.domain.progress import ProgressState


@dataclass
class ExecutionResult:
    """Result of a full stage execution, including any follow-up rounds."""

    output: str
    stage_result: "StageResult | None"
    stats: StageRunStats
    success: bool
    error: str | None = None
    milestones: list[Any] = field(default_factory=list)
    progress: "ProgressState | None" = None


__all__ = ["ExecutionResult"]
