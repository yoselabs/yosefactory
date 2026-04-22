"""SPEC stage — collaborative requirements + planning."""

from __future__ import annotations

from a2sdlc.config import StageConfig
from a2sdlc.domain.models import StageName, StageStatus

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


class SpecStage:
    name = StageName.SPEC
    uses_ai = True
    valid_statuses = frozenset({StageStatus.COMPLETE, StageStatus.QUESTIONS})
    config = StageConfig(
        name="spec",
        max_turns=150,
        timeout_minutes=30,
        allowed_tools=list(_DEFAULT_TOOLS),
    )
