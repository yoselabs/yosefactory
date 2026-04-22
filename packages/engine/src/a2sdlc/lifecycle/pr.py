"""PRLifecycle — manages draft PR creation, updates, and merge gate."""

from __future__ import annotations

from a2sdlc.adapters.retry import must_succeed
from a2sdlc.adapters.review import Approval, ReviewAdapter, ReviewComment


class PRLifecycle:
    """Manages the lifecycle of a pull request through the pipeline."""

    def __init__(self, review: ReviewAdapter) -> None:
        self._review = review

    def create_draft(self, branch: str, base: str, ticket_key: str) -> int:
        """Create a draft PR with a placeholder title. Returns the PR number."""
        title = f"agent/{ticket_key}"
        return must_succeed(
            lambda: self._review.create_draft_pr(
                branch=branch,
                base=base,
                title=title,
                ticket_key=ticket_key,
            )
        )

    def post_review(self, pr_number: int, body: str, verdict: str) -> None:
        """Post a review on a PR."""
        self._review.post_review(pr_number, body, verdict)

    def check_human_approval(self, pr_number: int) -> bool:
        """Return True if at least one non-bot approval exists."""
        approvals: list[Approval] = self._review.get_approvals(pr_number)
        return any(not a.is_bot for a in approvals)

    def update_title(self, pr_number: int, title: str) -> None:
        """Set the PR title — called before merge so the squash-merged
        commit on base reflects the ticket title rather than the bare
        `agent/<key>` placeholder from draft creation.
        """
        must_succeed(lambda: self._review.update_pr_title(pr_number, title))

    def merge(self, pr_number: int, method: str = "squash") -> None:
        """Mark the PR ready for review, then merge it."""
        must_succeed(lambda: self._review.mark_pr_ready(pr_number))
        must_succeed(lambda: self._review.merge_pr(pr_number, method))

    def read_context(self, pr_number: int) -> str:
        """Build a context string from the PR diff and review comments."""
        diff = self._review.read_pr_diff(pr_number)
        comments: list[ReviewComment] = self._review.read_pr_comments(pr_number)

        formatted_comments = "".join(
            f"**{c.author}** ({c.created_at}):\n{c.body}\n" for c in comments
        )

        return f"## PR Diff\n\n{diff}\n\n## Review Comments\n\n{formatted_comments}"
