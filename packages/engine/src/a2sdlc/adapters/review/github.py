"""GitHubReviewAdapter — ReviewAdapter impl backed by PyGithub."""

from __future__ import annotations

import logging
from datetime import datetime

from github.Repository import Repository

from a2sdlc.adapters.review import Approval, ReviewComment
from a2sdlc.domain.handover import (
    FeedbackItem,
    HandoverComment,
    parse_handover,
)

logger = logging.getLogger(__name__)


class GitHubReviewAdapter:
    """ReviewAdapter backed by GitHub PRs via PyGithub."""

    def __init__(self, repo: Repository) -> None:
        self._repo = repo

    def create_draft_pr(
        self, branch: str, base: str, title: str, ticket_key: str
    ) -> int:
        # Reuse an existing open PR for this branch if one exists — lets the
        # SPEC stage be re-entered after a partial failure without 422ing on
        # "A pull request already exists for <owner>:<branch>".
        owner_branch = f"{self._repo.owner.login}:{branch}"
        for existing in self._repo.get_pulls(state="open", head=owner_branch):
            logger.debug(
                "reusing existing open PR #%d for branch %s", existing.number, branch
            )
            return existing.number

        body = f"Closes #{ticket_key}"
        pr = self._repo.create_pull(
            title=title, body=body, head=branch, base=base, draft=True
        )
        logger.debug("created draft PR #%d for %s", pr.number, ticket_key)
        return pr.number

    def update_pr(self, pr_number: int, title: str, body: str, ticket_key: str) -> None:
        pull = self._repo.get_pull(pr_number)
        full_body = f"{body}\n\nCloses #{ticket_key}"
        pull.edit(title=title, body=full_body)
        logger.debug("updated PR #%d", pr_number)

    def mark_pr_ready(self, pr_number: int) -> None:
        self._repo._requester.requestJsonAndCheck(  # noqa: SLF001
            "PATCH",
            f"{self._repo.url}/pulls/{pr_number}",
            input={"draft": False},
        )
        logger.debug("marked PR #%d as ready", pr_number)

    def merge_pr(self, pr_number: int, method: str = "squash") -> None:
        pull = self._repo.get_pull(pr_number)
        pull.merge(merge_method=method)
        logger.debug("merged PR #%d via %s", pr_number, method)

    def get_approvals(self, pr_number: int) -> list[Approval]:
        pull = self._repo.get_pull(pr_number)
        approvals: list[Approval] = []
        for review in pull.get_reviews():
            if review.state == "APPROVED":
                user = review.user
                is_bot = user.type == "Bot" if user else False
                approvals.append(
                    Approval(user=user.login if user else "", is_bot=is_bot)
                )
        return approvals

    def post_review(self, pr_number: int, body: str, verdict: str) -> None:
        pull = self._repo.get_pull(pr_number)
        try:
            pull.create_review(body=body, event=verdict)
            logger.debug("posted review %s on PR #%d", verdict, pr_number)
        except Exception:  # noqa: BLE001
            logger.warning(
                "post_review failed for PR #%d, falling back to comment",
                pr_number,
                exc_info=True,
            )
            pull.create_issue_comment(f"**Review: {verdict}**\n\n{body}")

    def read_pr_diff(self, pr_number: int) -> str:
        pull = self._repo.get_pull(pr_number)
        files = pull.get_files()
        parts: list[str] = []
        for f in files:
            parts.append(f"--- {f.filename}\n{f.patch or ''}")
        return "\n".join(parts)

    def read_pr_comments(self, pr_number: int) -> list[ReviewComment]:
        pull = self._repo.get_pull(pr_number)
        comments: list[ReviewComment] = []
        for c in pull.get_issue_comments():
            comments.append(
                ReviewComment(
                    author=c.user.login if c.user else "",
                    body=c.body or "",
                    created_at=c.created_at.isoformat() if c.created_at else "",
                )
            )
        return comments

    def collect_pr_feedback(
        self, pr_number: int, since: datetime
    ) -> list[FeedbackItem]:
        """Collect feedback comments on a PR since a given time."""
        pull = self._repo.get_pull(pr_number)
        items: list[FeedbackItem] = []

        # PR reviews (always included — no mention filter needed)
        for review in pull.get_reviews():
            submitted = review.submitted_at
            if submitted and submitted <= since:
                continue
            user = review.user
            if user and user.type == "Bot":
                continue
            if not review.body:
                continue
            items.append(
                FeedbackItem(
                    id=str(review.id),
                    author=user.login if user else "",
                    author_type="human",
                    source="pr_review",
                    body=review.body,
                    created_at=submitted or since,
                )
            )

        # PR review comments (inline — file/line metadata)
        for comment in pull.get_review_comments():
            if comment.created_at <= since:
                continue
            user = comment.user
            if user and user.type == "Bot":
                continue
            items.append(
                FeedbackItem(
                    id=str(comment.id),
                    author=user.login if user else "",
                    author_type="human",
                    source="pr_inline",
                    body=comment.body or "",
                    file_path=comment.path,
                    line_range=(comment.line or 0, comment.line or 0),
                    created_at=comment.created_at,
                )
            )

        return items

    def find_last_handover(self, pr_number: int) -> HandoverComment | None:
        """Find the last handover comment on a PR."""
        issue = self._repo.get_issue(pr_number)
        best: HandoverComment | None = None
        for comment in issue.get_comments():
            parsed = parse_handover(
                comment.body or "",
                str(comment.id),
                comment.created_at,
                "pr",
            )
            if parsed is not None:
                if best is None or parsed.created_at > best.created_at:
                    best = parsed
        return best


__all__ = ["GitHubReviewAdapter"]
