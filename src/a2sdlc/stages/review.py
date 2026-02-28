"""REVIEW stage — independent PR review."""

from __future__ import annotations

from a2sdlc.config import StageConfig
from a2sdlc.models import StageAction, StageStatus


class ReviewStage:
    name = "review"
    uses_ai = True
    valid_statuses = frozenset({StageStatus.APPROVED, StageStatus.CHANGES_REQUESTED})
    config = StageConfig(
        name="review",
        max_turns=25,
        timeout_minutes=20,
        allowed_tools=["Bash", "Read", "Glob", "Grep", "WebFetch", "WebSearch"],
    )

    def resolve(
        self,
        status: StageStatus,
        comment_body: str,
        cost_footer: str,
        **kwargs: object,
    ) -> StageAction:
        auto_merge = bool(kwargs.get("auto_merge", False))
        raw_pr = kwargs.get("pr_number")
        pr_number: int | None = None
        if raw_pr is not None and isinstance(raw_pr, int):
            pr_number = raw_pr
        if status == StageStatus.APPROVED:
            return StageAction(
                comment=f"{comment_body}\n\n{cost_footer}",
                post_review=(pr_number, comment_body, "APPROVE") if pr_number else None,
                merge_pr=pr_number if auto_merge else None,
            )
        if status == StageStatus.CHANGES_REQUESTED:
            return StageAction(
                comment=f"{comment_body}\n\n{cost_footer}",
                post_review=(pr_number, comment_body, "REQUEST_CHANGES")
                if pr_number
                else None,
                transition_to="needs-fix",
            )
        return StageAction(
            comment=f"⚠️ Unexpected status {status} for review\n\n{cost_footer}",
        )
