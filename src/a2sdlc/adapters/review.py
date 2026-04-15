"""ReviewAdapter protocol and supporting types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from a2sdlc.handover import FeedbackItem, HandoverComment


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


__all__ = ["Approval", "ReviewComment", "ReviewAdapter"]
