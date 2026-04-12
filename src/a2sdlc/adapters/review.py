"""Review adapter protocol — PR/code review operations for pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ReviewComment:
    """A single comment on a pull request."""

    author: str
    body: str
    path: str | None = None
    line: int | None = None


@dataclass(frozen=True)
class Approval:
    """A PR review approval or change request."""

    author: str
    state: str  # "APPROVED" | "CHANGES_REQUESTED" | "COMMENTED"
    body: str = ""


class ReviewAdapter(Protocol):
    """Platform-specific code review operations.

    Handles PR lifecycle: create draft → update → mark ready → review → merge.
    """

    def get_diff(self, pr_number: int) -> str:
        """Return the unified diff for the given PR."""
        ...

    def get_comments(self, pr_number: int) -> list[ReviewComment]:
        """Return all review comments on the PR."""
        ...

    def get_approvals(self, pr_number: int) -> list[Approval]:
        """Return all reviews (approvals and change requests) on the PR."""
        ...

    def create_draft_pr(
        self,
        title: str,
        body: str,
        head: str,
        base: str,
    ) -> int:
        """Create a draft PR. Returns the PR number."""
        ...

    def update_pr(self, pr_number: int, title: str, body: str) -> None:
        """Update the PR title and/or body."""
        ...

    def mark_ready(self, pr_number: int) -> None:
        """Convert a draft PR to ready-for-review."""
        ...

    def post_review(self, pr_number: int, body: str, event: str) -> None:
        """Post a review (APPROVE or REQUEST_CHANGES)."""
        ...

    def merge_pr(self, pr_number: int, method: str = "squash") -> None:
        """Merge the PR using the specified method."""
        ...
