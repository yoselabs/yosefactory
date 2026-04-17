"""Normalized result from a stage execution.

Lives in domain/ because it crosses the pipeline ↔ adapters boundary
(the StageRunner port in adapters/protocols.py returns it).

The ``progress`` field carries an ``evaluation.progress.ProgressState``
at runtime, typed opaquely here to keep domain/ free of evaluation imports.
Consumers that need progress structure cast or import ProgressState directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    # Runtime type: evaluation.progress.ProgressState | None. Opaque here to
    # preserve domain purity — consumers in evaluation/pipeline cast as needed.
    progress: Any = None
