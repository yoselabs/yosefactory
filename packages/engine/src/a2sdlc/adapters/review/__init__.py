"""ReviewAdapter Protocol + Approval/ReviewComment data + in-tree review impls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from a2sdlc.domain.handover import FeedbackItem, HandoverComment
from a2sdlc.domain.stage_outcome import InlineComment


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
    def update_pr_title(self, pr_number: int, title: str) -> None:
        """Set the PR title without touching the body.

        Called by the engine right before merge so the squash-merged
        commit on base carries the ticket intent, not the branch-derived
        placeholder title. Distinct from `update_pr` so we don't have to
        re-construct the body + Closes-link text every time.
        """
        ...

    def mark_pr_ready(self, pr_number: int) -> None: ...
    def merge_pr(self, pr_number: int, method: str = "squash") -> None: ...
    def get_approvals(self, pr_number: int) -> list[Approval]: ...
    def post_review(self, pr_number: int, body: str, verdict: str) -> Path:
        """Post a review and return the local file path that mirrors the body.

        For LocalReviewAdapter, this *is* the canonical artifact. For GH /
        Jira ecosystems, the API call posts to the tracker and the
        returned path is a side-staging file the engine consults for the
        stdout output block.
        """
        ...

    def post_inline_comments(
        self, pr_number: int, comments: list[InlineComment]
    ) -> None:
        """Post per-line review comments on a PR (N1).

        Empty list must be a no-op — the REVIEW handler calls this
        unconditionally once it lands (P2 step 6), and the agent may
        legitimately produce zero inline comments. Implementations
        must validate comment file paths against the PR diff before
        submitting (N9 interim posture); out-of-diff entries are
        dropped with a warning, not fatal.
        """
        ...

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
from a2sdlc.adapters.review.local import LocalReviewAdapter  # noqa: E402
from a2sdlc.adapters.review.github import GitHubReviewAdapter  # noqa: E402

__all__ = [
    "Approval",
    "ReviewComment",
    "ReviewAdapter",
    "LocalNoopReviewAdapter",
    "LocalReviewAdapter",
    "GitHubReviewAdapter",
]
