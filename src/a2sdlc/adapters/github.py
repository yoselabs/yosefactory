"""GitHub ticket adapter — implements TicketAdapter via PyGithub."""

from __future__ import annotations

import json
import logging
import os

from github import Github

from a2sdlc.adapters.protocols import DispatchInput
from a2sdlc.exceptions import SkipEvent
from a2sdlc.models import StageName

logger = logging.getLogger("a2sdlc.adapters.github")


class GitHubTicketAdapter:
    """TicketAdapter backed by GitHub Issues + PRs via PyGithub."""

    STAGE_LABELS: dict[StageName, str] = {
        StageName.SPEC: "stage:spec",
        StageName.IMPLEMENT: "stage:implement",
        StageName.REVIEW: "stage:review",
        StageName.MERGE: "stage:merge",
    }
    TRIGGER_LABEL = "agent"
    BLOCKED_LABEL = "stage:blocked"
    DONE_LABEL = "stage:done"
    NEEDS_INPUT_LABEL = "needs-input"
    PROCEED_LABEL = "proceed"

    # Label → (flag_name, value) for override resolution
    LABEL_FLAG_MAP: dict[str, tuple[str, bool]] = {
        "auto-spec": ("auto_spec", True),
        "auto-merge": ("auto_merge", True),
        "spec-only": ("auto_proceed", False),
    }

    # Reverse lookup: label string → StageName
    _LABEL_TO_STAGE: dict[str, StageName] = {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)

    def __init__(self, repo_name: str, token: str) -> None:
        self._gh = Github(token)
        self._repo = self._gh.get_repo(repo_name)
        logger.debug("connected to repo %s", repo_name)

    # ── class-level reverse label map ─────────────────────────────────

    @classmethod
    def _label_to_stage(cls) -> dict[str, StageName]:
        """Build reverse lookup from STAGE_LABELS (cached on class)."""
        if not cls._LABEL_TO_STAGE:
            cls._LABEL_TO_STAGE = {v: k for k, v in cls.STAGE_LABELS.items()}
        return cls._LABEL_TO_STAGE

    # ── parse_event ────────────────────────────────────────────────────

    def parse_event(self) -> DispatchInput:
        """Read $GITHUB_EVENT_PATH + $GITHUB_EVENT_NAME and return DispatchInput.

        Raises SkipEvent for events that should not trigger the pipeline.
        """
        event_path = os.environ["GITHUB_EVENT_PATH"]
        event_name = os.environ["GITHUB_EVENT_NAME"]

        with open(event_path) as f:
            event = json.load(f)

        sender_type = event.get("sender", {}).get("type", "")
        if sender_type == "Bot":
            raise SkipEvent("bot sender")

        if event_name == "issues":
            return self._parse_issues_event(event)
        elif event_name == "issue_comment":
            return self._parse_issue_comment_event(event)
        elif event_name == "pull_request":
            return self._parse_pull_request_event(event)
        else:
            raise SkipEvent(f"unsupported event name: {event_name!r}")

    def _parse_issues_event(self, event: dict) -> DispatchInput:
        action = event.get("action")
        if action != "labeled":
            raise SkipEvent(f"issues action {action!r} is not 'labeled'")

        label_name = event["label"]["name"]
        issue_number = str(event["issue"]["number"])

        if label_name == self.TRIGGER_LABEL:
            return DispatchInput(key=issue_number, stage=StageName.SPEC)

        if label_name == self.PROCEED_LABEL:
            return DispatchInput(key=issue_number, stage=StageName.IMPLEMENT)

        label_map = self._label_to_stage()
        if label_name in label_map:
            stage = label_map[label_name]
            pr_number = None
            # Review stage needs a PR — look it up from the agent branch.
            if stage == StageName.REVIEW:
                pr_number = self.get_pr_for_branch(f"agent/{issue_number}")
                if pr_number is None:
                    raise SkipEvent(
                        f"stage:review on issue {issue_number} but no PR found for agent/{issue_number}"
                    )
                logger.info(
                    "review triggered from issue label, resolved PR #%d",
                    pr_number,
                )
            return DispatchInput(key=issue_number, stage=stage, pr_number=pr_number)

        raise SkipEvent(f"label {label_name!r} is not a stage label")

    def _parse_issue_comment_event(self, event: dict) -> DispatchInput:
        issue_labels = {lbl["name"] for lbl in event.get("issue", {}).get("labels", [])}
        issue_number = str(event["issue"]["number"])

        if self.NEEDS_INPUT_LABEL not in issue_labels:
            raise SkipEvent("issue_comment but issue does not have needs-input label")

        return DispatchInput(
            key=issue_number,
            stage=StageName.SPEC,
            is_resume=True,
        )

    def _parse_pull_request_event(self, event: dict) -> DispatchInput:
        action = event.get("action")
        if action != "labeled":
            raise SkipEvent(f"pull_request action {action!r} is not 'labeled'")

        label_name = event["label"]["name"]
        label_map = self._label_to_stage()

        if label_name not in label_map or label_map[label_name] != StageName.REVIEW:
            raise SkipEvent(f"label {label_name!r} is not stage:review")

        pr_number = event["pull_request"]["number"]
        return DispatchInput(
            key=str(pr_number),
            stage=StageName.REVIEW,
            pr_number=pr_number,
        )

    # ── ticket access ─────────────────────────────────────────────────

    def get_ticket(self, key: str) -> str:
        """Return issue body for spec/implement, or PR summary for review.

        Pass key as "pr:<number>" for PR access.
        """
        if key.startswith("pr:"):
            pr_number = int(key[3:])
            pull = self._repo.get_pull(pr_number)
            files = [f.filename for f in pull.get_files()]
            files_list = "\n".join(f"- {fn}" for fn in files)
            return (
                f"# {pull.title}\n\n{pull.body or ''}\n\n## Changed files\n{files_list}"
            )

        issue = self._repo.get_issue(int(key))
        return issue.body or ""

    def get_labels(self, key: str) -> list[str]:
        """Return label names from issue."""
        issue = self._repo.get_issue(int(key))
        return [lbl.name for lbl in issue.labels]

    # ── comments ──────────────────────────────────────────────────────

    def post_comment(self, key: str, body: str) -> str:
        """Post a comment on an issue. Returns the comment ID as string."""
        issue = self._repo.get_issue(int(key))
        comment = issue.create_comment(body)
        logger.debug("posted comment %s on issue %s", comment.id, key)
        return str(comment.id)

    def update_comment(self, key: str, comment_id: str, body: str) -> None:
        """Edit an existing comment by ID."""
        issue = self._repo.get_issue(int(key))
        comment = issue.get_comment(int(comment_id))
        comment.edit(body)
        logger.debug("updated comment %s on issue %s", comment_id, key)

    # ── labels ────────────────────────────────────────────────────────

    def set_stage_label(self, key: str, stage: StageName) -> None:
        """Remove all existing stage:* labels and add the new one."""
        issue = self._repo.get_issue(int(key))
        stage_prefix = "stage:"
        for label in issue.labels:
            if label.name.startswith(stage_prefix):
                issue.remove_from_labels(label)
        new_label = self.STAGE_LABELS[stage]
        issue.add_to_labels(new_label)
        logger.debug("set stage label %s on issue %s", new_label, key)

    def set_done_label(self, key: str) -> None:
        """Add the done label to an issue."""
        issue = self._repo.get_issue(int(key))
        issue.add_to_labels(self.DONE_LABEL)
        logger.debug("set done label on issue %s", key)

    def set_blocked(self, key: str, reason: str) -> None:
        """Add blocked label and post a comment explaining why."""
        issue = self._repo.get_issue(int(key))
        issue.add_to_labels(self.BLOCKED_LABEL)
        issue.create_comment(f"Blocked: {reason}")
        logger.debug("set blocked on issue %s: %s", key, reason)

    # ── PR operations ─────────────────────────────────────────────────

    def post_review(self, pr: int, body: str, event: str) -> None:
        """Post a review (APPROVE or REQUEST_CHANGES) on a PR.

        Falls back to a comment if the review fails (e.g., can't approve own PR).
        """
        pull = self._repo.get_pull(pr)
        try:
            pull.create_review(body=body, event=event)
            logger.debug("posted review %s on PR %s", event, pr)
        except Exception:  # noqa: BLE001
            logger.warning(
                "post_review failed for PR %s, falling back to comment",
                pr,
                exc_info=True,
            )
            pull.create_issue_comment(f"**Review: {event}**\n\n{body}")

    def get_pr_for_branch(self, branch: str) -> int | None:
        """Find an open PR by head branch name. Returns PR number or None."""
        pulls = self._repo.get_pulls(state="open", head=branch)
        for pr in pulls:
            return pr.number
        return None

    def merge_pr(self, pr: int, method: str = "squash") -> None:
        """Merge a PR using the specified method (squash, merge, rebase)."""
        pull = self._repo.get_pull(pr)
        pull.merge(merge_method=method)
        logger.debug("merged PR %s via %s", pr, method)
