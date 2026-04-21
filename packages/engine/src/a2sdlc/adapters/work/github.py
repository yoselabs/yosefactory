"""GitHubWorkAdapter — WorkAdapter impl backed by GitHub Issues via PyGithub."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime

from github.Repository import Repository

from a2sdlc.domain.pipeline_event import PipelineEvent
from a2sdlc.domain.exceptions import SkipEvent
from a2sdlc.domain.handover import (
    HANDOVER_PATTERN,
    FeedbackItem,
    HandoverComment,
    parse_handover,
)
from a2sdlc.domain.models import StageName

logger = logging.getLogger(__name__)

# ── Label constants (used only by GitHubWorkAdapter) ──────────────────

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


# ── GitHubWorkAdapter ─────────────────────────────────────────────────


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
        if action == "closed":
            # A human closing the issue is a terminal signal. Return a
            # marker event so dispatch can clean up (strip stage:* labels,
            # set stage:done) without running any AI stage. Contract-level
            # `is_ticket_active` will then short-circuit any later stale
            # events for this ticket.
            return PipelineEvent(
                key=str(event["issue"]["number"]),
                trigger_stage=None,
                is_feedback=False,
                pr_number=None,
                is_closed=True,
            )
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

    def is_ticket_active(self, key: str) -> bool:
        """False if the issue (or PR) is closed/merged.

        GitHub's Issues API resolves both issues and PRs by number — a merged
        or closed PR surfaces as an Issue with state=="closed".
        """
        issue = self._repo.get_issue(int(key))
        return issue.state != "closed"

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

    def get_current_stage(self, key: str) -> StageName | None:
        """Return the stage implied by the issue's `stage:*` label, or None."""
        issue = self._repo.get_issue(int(key))
        for label in issue.labels:
            if label.name in _LABEL_TO_STAGE:
                return _LABEL_TO_STAGE[label.name]
        return None

    def set_current_stage(self, key: str, stage: StageName) -> None:
        """Remove all existing stage:* labels + the trigger label, add the new stage."""
        issue = self._repo.get_issue(int(key))
        stage_prefix = "stage:"
        # Also clear the trigger label once a stage:* is active — the engine
        # has picked the ticket up; keeping `agent` around is cosmetic noise
        # that misleads humans scanning the board.
        for label in issue.labels:
            if label.name.startswith(stage_prefix) or label.name == TRIGGER_LABEL:
                issue.remove_from_labels(label)
        new_label = STAGE_LABELS[stage]
        issue.add_to_labels(new_label)
        logger.debug("set stage label %s on issue %s", new_label, key)

    def mark_done(self, key: str) -> None:
        """Mark the ticket done: close the issue + strip transient labels.

        For tracker-agnostic parity (Jira's "Done" status is the native
        analog), the done signal IS the closed-issue state. We no longer
        add a separate `stage:done` label — it was redundant with the
        issue's closed state and had no Jira equivalent.
        """
        issue = self._repo.get_issue(int(key))
        for label in issue.labels:
            if label.name.startswith("stage:") or label.name == TRIGGER_LABEL:
                issue.remove_from_labels(label)
        # Close the issue if the engine completed on its own (e.g. AUTO
        # merge hadn't happened yet, or non-merge done paths). Idempotent —
        # closing an already-closed issue is a no-op.
        if issue.state != "closed":
            issue.edit(state="closed")
        logger.debug("marked issue %s done (closed + stripped labels)", key)

    def mark_blocked(self, key: str, reason: str) -> None:
        """Add blocked label and post a comment explaining why.

        Idempotent: checks for an existing recent "Blocked: <reason>"
        comment by the bot and skips posting a duplicate. Label addition is
        already idempotent on the GH side (adding an existing label is a
        no-op).
        """
        issue = self._repo.get_issue(int(key))
        issue.add_to_labels(BLOCKED_LABEL)
        marker = f"Blocked: {reason}"
        # Scan the last handful of comments for an identical blocked notice.
        # GH returns issue comments oldest-first; page backwards for speed.
        try:
            comments = list(issue.get_comments())
            for c in reversed(comments[-10:]):
                body = c.body or ""
                if body.strip().startswith(marker):
                    logger.debug("mark_blocked: duplicate suppressed for issue %s", key)
                    return
        except Exception:  # noqa: BLE001
            # If the listing fails, fall through and post — a duplicate is
            # better than a missing signal.
            logger.debug("mark_blocked: dedup check failed", exc_info=True)
        issue.create_comment(marker)
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


__all__ = ["GitHubWorkAdapter"]
