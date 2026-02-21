"""SPEC stage — collaborative requirements + planning."""

from __future__ import annotations

from a2sdlc.config import StageConfig
from a2sdlc.models import StageAction, StageStatus

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
    name = "spec"
    uses_ai = True
    valid_statuses = frozenset({StageStatus.COMPLETE, StageStatus.QUESTIONS})
    config = StageConfig(
        name="spec",
        max_turns=35,
        timeout_minutes=30,
        allowed_tools=list(_DEFAULT_TOOLS),
    )

    def resolve(
        self,
        status: StageStatus,
        comment_body: str,
        cost_footer: str,
        **kwargs: object,
    ) -> StageAction:
        if status == StageStatus.COMPLETE:
            return StageAction(
                comment=f"{comment_body}\n\n{cost_footer}",
                write_state=("spec", "complete"),
            )
        if status == StageStatus.QUESTIONS:
            return StageAction(
                comment=f"{comment_body}\n\n{cost_footer}",
                transition_to="needs-input",
            )
        return StageAction(
            comment=f"⚠️ Unexpected status {status} for spec\n\n{cost_footer}",
        )
