"""IMPLEMENT stage — autonomous code implementation."""

from __future__ import annotations

from a2sdlc.config import StageConfig
from a2sdlc.models import StageName, StageStatus, Transition

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
    transitions: dict[StageStatus, Transition] = {
        StageStatus.COMPLETE: Transition(
            next=StageName.REVIEW,
        ),
        StageStatus.QUESTIONS: Transition(
            next=None,
        ),
    }
    config = StageConfig(
        name="implement",
        max_turns=120,
        timeout_minutes=60,
        allowed_tools=list(_DEFAULT_TOOLS),
    )
