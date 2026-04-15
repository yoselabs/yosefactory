"""GitHub adapters — WorkAdapter + ReviewAdapter via PyGithub."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime

from github import Github
from github.Repository import Repository

from a2sdlc.adapters.review import Approval, ReviewComment
from a2sdlc.adapters.work import PipelineEvent
from a2sdlc.exceptions import SkipEvent
from a2sdlc.handover import (
    HANDOVER_PATTERN,
    FeedbackItem,
    HandoverComment,
    parse_handover,
)
from a2sdlc.models import StageName

logger = logging.getLogger("a2sdlc.adapters.github")

# ── Constants ────────────────────────────────────────────────────────

STAGE_LABELS: dict[StageName, str] = {
    StageName.SPEC: "stage:spec",
    StageName.IMPLEMENT: "stage:implement",
    StageName.REVIEW: "stage:review",
    StageName.MERGE: "stage:merge",
}
_LABEL_TO_STAGE: dict[str, StageName] = {v: k for k, v in STAGE_LABELS.items()}

TRIGGER_LABEL = "agent"
BLOCKED_LABEL = "stage:blocked"
DONE_LABEL = "stage:done"
NEEDS_INPUT_LABEL = "needs-input"
PROCEED_LABEL = "proceed"


# ── WorkAdapter ──────────────────────────────────────────────────────


def connect(repo_name: str, token: str) -> Repository:
    """Create a shared PyGithub repo handle. Pass to both adapters."""
    return Github(token).get_repo(repo_name)


class GitHubWorkAdapter:
    """WorkAdapter backed by GitHub Issues via PyGithub."""

    def __init__(self, repo: Repository, trigger_mention: str = "@a2sdlc") -> None:
        self._repo = repo
        self._trigger_mention = trigger_mention

    # ── parse_event ──────────────────────────────────────────────────

    def parse_event(self) -> PipelineEvent:
        """Read $GITHUB_EVENT_PATH + $GITHUB_EVENT_NAME and return PipelineEvent.

        Raises SkipEvent for events that should not trigger the pipeline.
        """
        event_path = os.environ["GITHUB_EVENT_PATH"]
        event_name = os.environ["GITHUB_EVENT_NAME"]

        with open(event_path) as f:
            event = json.load(f)

        sender_type = event.get("sender", {}).get("type", "")

        if event_name == "issues":
            return self._parse_issues_event(event)
        elif event_name == "issue_comment":
            return self._parse_issue_comment_event(event, sender_type)
        elif event_name == "pull_request":
            return self._parse_pull_request_event(event)
        elif event_name == "pull_request_review":
            return self._parse_pr_review_event(event, sender_type)
        elif event_name == "pull_request_review_comment":
            return self._parse_pr_review_comment_event(event, sender_type)
        else:
            raise SkipEvent(f"unsupported event name: {event_name!r}")

    def _parse_issues_event(self, event: dict) -> PipelineEvent:
        action = event.get("action")
        if action != "labeled":
            raise SkipEvent(f"issues action {action!r} is not 'labeled'")

        label_name = event["label"]["name"]
        issue_number = str(event["issue"]["number"])

        if label_name == TRIGGER_LABEL:
            return PipelineEvent(key=issue_number, trigger_stage=StageName.SPEC)

        if label_name == PROCEED_LABEL:
            return PipelineEvent(
                key=issue_number, trigger_stage=None, is_feedback=False
            )

        if label_name in _LABEL_TO_STAGE:
            stage = _LABEL_TO_STAGE[label_name]
            pr_number = None
            # Review stage needs a PR — look it up from the agent branch.
            if stage == StageName.REVIEW:
                pr_number = self._get_pr_for_branch(f"agent/{issue_number}")
                if pr_number is None:
                    raise SkipEvent(
                        f"stage:review on issue {issue_number} but no PR found for agent/{issue_number}"
                    )
                logger.info(
                    "review triggered from issue label, resolved PR #%d",
                    pr_number,
                )
            return PipelineEvent(
                key=issue_number, trigger_stage=stage, pr_number=pr_number
            )

        raise SkipEvent(f"label {label_name!r} is not a stage label")

    def _parse_issue_comment_event(
        self, event: dict, sender_type: str
    ) -> PipelineEvent:
        if sender_type == "Bot":
            raise SkipEvent("bot comment sender")

        comment_body = event.get("comment", {}).get("body", "")
        issue_number = str(event["issue"]["number"])

        if self._trigger_mention not in comment_body:
            raise SkipEvent(f"comment does not contain {self._trigger_mention}")

        return PipelineEvent(
            key=issue_number,
            trigger_stage=None,
            is_feedback=True,
        )

    def _get_issue_key_for_pr(self, pr_number: int) -> str:
        """Extract the linked issue number from a PR's body.

        The adapter writes 'Closes #N' in the PR body when creating drafts.
        Falls back to the PR number if no linked issue is found.
        """
        pr = self._repo.get_pull(pr_number)
        body = str(pr.body) if pr.body else ""
        match = re.search(r"Closes #(\d+)", body)
        if match:
            return match.group(1)
        return str(pr_number)

    def _parse_pr_review_event(self, event: dict, sender_type: str) -> PipelineEvent:
        if sender_type == "Bot":
            raise SkipEvent("bot PR review sender")

        pr_number = event["pull_request"]["number"]
        key = self._get_issue_key_for_pr(pr_number)
        return PipelineEvent(
            key=key,
            trigger_stage=None,
            is_feedback=True,
            pr_number=pr_number,
        )

    def _parse_pr_review_comment_event(
        self, event: dict, sender_type: str
    ) -> PipelineEvent:
        if sender_type == "Bot":
            raise SkipEvent("bot PR review comment sender")

        comment_body = event.get("comment", {}).get("body", "")
        if self._trigger_mention not in comment_body:
            raise SkipEvent(f"PR comment does not contain {self._trigger_mention}")

        pr_number = event["pull_request"]["number"]
        key = self._get_issue_key_for_pr(pr_number)
        return PipelineEvent(
            key=key,
            trigger_stage=None,
            is_feedback=True,
            pr_number=pr_number,
        )

    def _parse_pull_request_event(self, event: dict) -> PipelineEvent:
        action = event.get("action")
        if action != "labeled":
            raise SkipEvent(f"pull_request action {action!r} is not 'labeled'")

        label_name = event["label"]["name"]

        if (
            label_name not in _LABEL_TO_STAGE
            or _LABEL_TO_STAGE[label_name] != StageName.REVIEW
        ):
            raise SkipEvent(f"label {label_name!r} is not stage:review")

        pr_number = event["pull_request"]["number"]
        return PipelineEvent(
            key=str(pr_number),
            trigger_stage=StageName.REVIEW,
            pr_number=pr_number,
        )

    def _get_pr_for_branch(self, branch: str) -> int | None:
        """Find an open PR by head branch name. Returns PR number or None."""
        pulls = self._repo.get_pulls(state="open", head=branch)
        for pr in pulls:
            return pr.number
        return None

    # ── ticket access ────────────────────────────────────────────────

    def get_ticket(self, key: str) -> str:
        """Return issue body."""
        issue = self._repo.get_issue(int(key))
        return issue.body or ""

    def get_labels(self, key: str) -> list[str]:
        """Return label names from issue."""
        issue = self._repo.get_issue(int(key))
        return [lbl.name for lbl in issue.labels]

    # ── comment lifecycle ────────────────────────────────────────────

    def begin_comment(self, key: str) -> str:
        """Post an initial comment on an issue. Returns the comment ID."""
        issue = self._repo.get_issue(int(key))
        comment = issue.create_comment("\u23f3 Starting...")
        logger.debug("begin_comment %s on issue %s", comment.id, key)
        return str(comment.id)

    def update_progress(self, comment_id: str, body: str) -> None:
        """Edit a comment by ID via repo-scoped REST endpoint.

        Uses PyGithub's internal requester because the public API
        (issue.get_comment) requires the issue number, which the
        WorkAdapter protocol intentionally doesn't pass here.
        """
        self._repo._requester.requestJsonAndCheck(  # noqa: SLF001
            "PATCH",
            f"{self._repo.url}/issues/comments/{comment_id}",
            input={"body": body},
        )

    def finalize_comment(self, comment_id: str, body: str) -> None:
        """Final edit of a comment — same as update but semantically final."""
        self.update_progress(comment_id, body)

    # ── labels ───────────────────────────────────────────────────────

    def set_stage_label(self, key: str, stage: StageName) -> None:
        """Remove all existing stage:* labels and add the new one."""
        issue = self._repo.get_issue(int(key))
        stage_prefix = "stage:"
        for label in issue.labels:
            if label.name.startswith(stage_prefix):
                issue.remove_from_labels(label)
        new_label = STAGE_LABELS[stage]
        issue.add_to_labels(new_label)
        logger.debug("set stage label %s on issue %s", new_label, key)

    def set_done_label(self, key: str) -> None:
        """Add the done label to an issue."""
        issue = self._repo.get_issue(int(key))
        issue.add_to_labels(DONE_LABEL)
        logger.debug("set done label on issue %s", key)

    def set_blocked(self, key: str, reason: str) -> None:
        """Add blocked label and post a comment explaining why."""
        issue = self._repo.get_issue(int(key))
        issue.add_to_labels(BLOCKED_LABEL)
        issue.create_comment(f"Blocked: {reason}")
        logger.debug("set blocked on issue %s: %s", key, reason)

    def format_branch(self, ticket_key: str) -> str:
        """Return branch name for a ticket."""
        return f"agent/{ticket_key}"

    def collect_issue_feedback(self, key: str, since: datetime) -> list[FeedbackItem]:
        """Collect feedback comments on an issue since a given time."""
        issue = self._repo.get_issue(int(key))
        items: list[FeedbackItem] = []
        for comment in issue.get_comments(since=since):
            body = comment.body or ""
            if self._trigger_mention not in body:
                continue
            if HANDOVER_PATTERN.search(body):
                continue  # Skip handover comments
            sender_type = (
                "bot" if (comment.user and comment.user.type == "Bot") else "human"
            )
            items.append(
                FeedbackItem(
                    id=str(comment.id),
                    author=comment.user.login if comment.user else "",
                    author_type=sender_type,
                    source="issue_comment",
                    body=body,
                    created_at=comment.created_at,
                )
            )
        return items

    def find_last_handover(self, key: str) -> HandoverComment | None:
        """Find the last handover comment on an issue."""
        issue = self._repo.get_issue(int(key))
        best: HandoverComment | None = None
        for comment in issue.get_comments():
            parsed = parse_handover(
                comment.body or "",
                str(comment.id),
                comment.created_at,
                "issue",
            )
            if parsed is not None:
                if best is None or parsed.created_at > best.created_at:
                    best = parsed
        return best


# ── ReviewAdapter ────────────────────────────────────────────────────


class GitHubReviewAdapter:
    """ReviewAdapter backed by GitHub PRs via PyGithub."""

    def __init__(self, repo: Repository) -> None:
        self._repo = repo

    def create_draft_pr(
        self, branch: str, base: str, title: str, ticket_key: str
    ) -> int:
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
