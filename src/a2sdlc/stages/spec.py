"""SPEC stage — collaborative requirements + planning."""

from __future__ import annotations

from a2sdlc.config import StageConfig
from a2sdlc.models import Gate, StageName, StageStatus, Transition

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


class SpecStage:
    name = StageName.SPEC
    uses_ai = True
    valid_statuses = frozenset({StageStatus.COMPLETE, StageStatus.QUESTIONS})
    transitions: dict[StageStatus, Transition] = {
        StageStatus.COMPLETE: Transition(
            next=StageName.IMPLEMENT,
            gate=Gate.AUTO_PROCEED,
        ),
        StageStatus.QUESTIONS: Transition(
            next=None,
        ),
    }
    config = StageConfig(
        name="spec",
        max_turns=35,
        timeout_minutes=30,
        allowed_tools=list(_DEFAULT_TOOLS),
    )
