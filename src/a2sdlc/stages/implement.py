"""IMPLEMENT stage — autonomous code implementation."""

from __future__ import annotations

from a2sdlc.config import StageConfig
from a2sdlc.models import StageAction, StageName, StageStatus, Transition

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
            label="stage:review",
            jira_status="In Review",
        ),
        StageStatus.QUESTIONS: Transition(
            next=None,
            label="needs-input",
        ),
    }
    config = StageConfig(
        name="implement",
        max_turns=120,
        timeout_minutes=60,
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
                write_state=(StageName.IMPLEMENT, StageStatus.COMPLETE),
            )
        if status == StageStatus.QUESTIONS:
            return StageAction(
                comment=f"{comment_body}\n\n{cost_footer}",
                transition_to="needs-input",
            )
        return StageAction(
            comment=f"⚠️ Unexpected status {status} for implement\n\n{cost_footer}",
        )
