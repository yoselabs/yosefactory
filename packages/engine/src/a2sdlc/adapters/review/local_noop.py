"""Local file-backed ReviewAdapter — PR state under `.a2sdlc/state/`.

Stand-in for GitHub PRs when running the engine fully offline. All PR state
(title, body, status, reviews) is persisted to `.a2sdlc/state/pr.json`.
Feedback written by `post_review(verdict='changes_requested')` lands in
`.a2sdlc/state/feedback.json` with a `consumed=false` flag the runner flips
after a successful IMPLEMENT dispatch. The whole `.a2sdlc/state/` folder
is opaque runtime data and stripped pre-merge.
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from a2sdlc.adapters.review import Approval, ReviewComment
from a2sdlc.domain.handover import FeedbackItem, HandoverComment

logger = logging.getLogger(__name__)

_PR_FILE = "pr.json"
_FEEDBACK_FILE = "feedback.json"


class LocalNoopReviewAdapter:
    """File-backed mock of the ReviewAdapter protocol."""

    def __init__(self, project_root: Path) -> None:
        self._root = project_root
        self._state_dir = project_root / ".a2sdlc" / "state"
        self._state_dir.mkdir(parents=True, exist_ok=True)

    # ── internal helpers ─────────────────────────────────────────────

    @property
    def _pr_path(self) -> Path:
        return self._state_dir / _PR_FILE

    @property
    def _feedback_path(self) -> Path:
        return self._state_dir / _FEEDBACK_FILE

    def _read_pr(self) -> dict[str, Any]:
        return json.loads(self._pr_path.read_text())

    def _write_pr(self, data: dict[str, Any]) -> None:
        self._pr_path.write_text(json.dumps(data, indent=2))

    # ── protocol methods ─────────────────────────────────────────────

    def create_draft_pr(
        self, branch: str, base: str, title: str, ticket_key: str
    ) -> int:
        """Initialize pr.json with pr_number=1 and status=draft. Returns 1."""
        data: dict[str, Any] = {
            "pr_number": 1,
            "status": "draft",
            "branch": branch,
            "base": base,
            "ticket_key": ticket_key,
            "title": title,
            "body": "",
            "reviews": [],
        }
        self._write_pr(data)
        logger.debug("created draft PR #1 for %s", ticket_key)
        return 1

    def update_pr(self, pr_number: int, title: str, body: str, ticket_key: str) -> None:
        """Update pr.json title/body/ticket_key."""
        data = self._read_pr()
        data["title"] = title
        data["body"] = body
        data["ticket_key"] = ticket_key
        self._write_pr(data)

    def update_pr_title(self, pr_number: int, title: str) -> None:
        """Update pr.json title only (leave body + ticket_key intact)."""
        data = self._read_pr()
        data["title"] = title
        self._write_pr(data)

    def mark_pr_ready(self, pr_number: int) -> None:
        """Set status='ready'."""
        data = self._read_pr()
        data["status"] = "ready"
        self._write_pr(data)

    def merge_pr(self, pr_number: int, method: str = "squash") -> None:
        """Set status='merged'."""
        data = self._read_pr()
        data["status"] = "merged"
        self._write_pr(data)

    def get_approvals(self, pr_number: int) -> list[Approval]:
        """Return a single synthetic local human approval."""
        return [Approval(user="local", is_bot=False)]

    def post_review(self, pr_number: int, body: str, verdict: str) -> None:
        """Append a review to pr.json. If changes_requested, also write feedback.json."""
        data = self._read_pr()
        reviews: list[dict[str, Any]] = data.setdefault("reviews", [])
        cycle = len(reviews) + 1
        created_at = datetime.now(timezone.utc).isoformat()
        review_record = {
            "cycle": cycle,
            "verdict": verdict,
            "body": body,
            "created_at": created_at,
        }
        reviews.append(review_record)
        self._write_pr(data)

        if verdict == "changes_requested":
            feedback_record = {
                "consumed": False,
                "body": body,
                "cycle": cycle,
                "created_at": created_at,
            }
            self._feedback_path.write_text(json.dumps(feedback_record, indent=2))

    def read_pr_diff(self, pr_number: int) -> str:
        """Shell out to `git diff <base>..HEAD` in project_root."""
        data = self._read_pr()
        base = data.get("base", "main")
        result = subprocess.run(
            ["git", "diff", f"{base}..HEAD"],
            cwd=self._root,
            capture_output=True,
            text=True,
        )
        return result.stdout

    def read_pr_comments(self, pr_number: int) -> list[ReviewComment]:
        """Map pr.json reviews to ReviewComment objects."""
        data = self._read_pr()
        return [
            ReviewComment(
                author="local",
                body=r.get("body", ""),
                created_at=r.get("created_at", ""),
            )
            for r in data.get("reviews", [])
        ]

    def collect_pr_feedback(
        self, pr_number: int, since: datetime
    ) -> list[FeedbackItem]:
        """Return feedback as a list of one item, or empty.

        Returns empty list when:
        - feedback.json doesn't exist
        - feedback is already consumed
        - feedback created_at <= since

        This adapter is read-only — does NOT flip the consumed flag.
        """
        if not self._feedback_path.exists():
            return []

        fb = json.loads(self._feedback_path.read_text())
        if fb.get("consumed", False):
            return []

        created_at = _parse_iso(fb["created_at"])
        if created_at <= _ensure_aware(since):
            return []

        return [
            FeedbackItem(
                id=f"local-fb-{fb.get('cycle', 1)}",
                author="local",
                author_type="human",
                source="pr_review",
                body=fb.get("body", ""),
                created_at=created_at,
            )
        ]

    def find_last_handover(self, pr_number: int) -> HandoverComment | None:
        """PR-side handover is not used in local mode."""
        return None

    # ── runner helper (NOT part of the ReviewAdapter protocol) ───────

    def mark_feedback_consumed(self) -> None:
        """Flip consumed=true in feedback.json. Called by runner after IMPLEMENT."""
        if not self._feedback_path.exists():
            return
        fb = json.loads(self._feedback_path.read_text())
        fb["consumed"] = True
        self._feedback_path.write_text(json.dumps(fb, indent=2))


# ── ISO datetime helpers ─────────────────────────────────────────────


def _parse_iso(value: str) -> datetime:
    """Parse an ISO datetime string; assume UTC if no tz info."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _ensure_aware(dt: datetime) -> datetime:
    """Return a tz-aware datetime; assume UTC if naive."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


__all__ = ["LocalNoopReviewAdapter"]
