"""IMPLEMENT stage — autonomous code implementation."""

from __future__ import annotations

from a2sdlc.config import StageConfig
from a2sdlc.models import StageName, StageStatus

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
]


class ImplementStage:
    name = StageName.IMPLEMENT
    uses_ai = True
    valid_statuses = frozenset({StageStatus.COMPLETE, StageStatus.QUESTIONS})
    config = StageConfig(
        name="implement",
        max_turns=150,
        timeout_minutes=60,
        allowed_tools=list(_DEFAULT_TOOLS),
    )
