"""Stage and dispatch result types.

Both live in domain/ because they cross layer boundaries:
- ``RunResult`` returned by the ``StageRunner`` port (adapters/runner/).
- ``DispatchResult`` returned by ``pipeline/dispatch.py``, consumed by
  CLI and evaluation layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from a2sdlc.domain.models import StageName, StageStatus
from a2sdlc.domain.stats import StageRunStats


@dataclass
class RunResult:
    """Normalized result from a stage execution."""

    success: bool
    output: str = ""
    error: str | None = None
    session_id: str = ""
    total_cost_usd: float = 0.0
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    num_turns: int = 0
    tool_log: list[str] = field(default_factory=list)
    # Runtime type: domain.progress.ProgressState | None. Opaque here to
    # avoid a cyclic import — consumers cast as needed.
    progress: Any = None


@dataclass
class DispatchResult:
    """What happened during dispatch — for testing and logging."""

    stage: StageName
    status: StageStatus | None = None
    next_stage: StageName | None = None
    blocked: bool = False
    error: str | None = None
    # Cost/token telemetry from the stage run (only populated on success path).
    stats: StageRunStats | None = None
    # Raw agent output (runner's final message). Empty string on paths that
    # never reach the runner (e.g. early validation failures).
    output: str = ""
