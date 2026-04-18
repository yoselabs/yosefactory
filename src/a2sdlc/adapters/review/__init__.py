"""ReviewAdapter Protocol + Approval/ReviewComment data + in-tree review impls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from a2sdlc.domain.handover import FeedbackItem, HandoverComment


@dataclass(frozen=True)
class Approval:
    """A PR approval record."""

    user: str
    is_bot: bool


@dataclass(frozen=True)
class ReviewComment:
    """A PR review comment."""

    author: str
    body: str
    created_at: str


class ReviewAdapter(Protocol):
    """Platform-specific pull-request operations."""

    def create_draft_pr(
        self, branch: str, base: str, title: str, ticket_key: str
    ) -> int: ...
    def update_pr(
        self, pr_number: int, title: str, body: str, ticket_key: str
    ) -> None: ...
    def mark_pr_ready(self, pr_number: int) -> None: ...
    def merge_pr(self, pr_number: int, method: str = "squash") -> None: ...
    def get_approvals(self, pr_number: int) -> list[Approval]: ...
    def post_review(self, pr_number: int, body: str, verdict: str) -> None: ...
    def read_pr_diff(self, pr_number: int) -> str: ...
    def read_pr_comments(self, pr_number: int) -> list[ReviewComment]: ...
    def collect_pr_feedback(
        self, pr_number: int, since: datetime
    ) -> list[FeedbackItem]: ...
    def find_last_handover(self, pr_number: int) -> HandoverComment | None: ...


# NOTE: impls below import Approval/ReviewComment (and ReviewAdapter) from this
# module. That works because Python sees those names as already-defined when
# it executes the import statements below. Keep these re-exports LAST —
# moving them above the dataclass/Protocol definitions above would break
# the partial-init chain with ImportError.
from a2sdlc.adapters.review.local_noop import LocalNoopReviewAdapter  # noqa: E402

__all__ = ["Approval", "ReviewComment", "ReviewAdapter", "LocalNoopReviewAdapter"]
