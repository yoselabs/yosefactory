"""GitHub Issues adapter — fetch, comment, transition via gh CLI."""

from __future__ import annotations

import json
import logging
import re

from a2sdlc.adapters._gh import gh
from a2sdlc.adapters.base import TicketAdapter

STATUS_LABELS = frozenset(
    {"needs-input", "prd-complete", "plan-complete", "implement-ready"}
)


class GitHubTickets(TicketAdapter):
    """TicketAdapter backed by GitHub Issues via the ``gh`` CLI."""

    def __init__(self, repo: str) -> None:
        self.repo = repo
        self.logger = logging.getLogger("a2sdlc.adapters.github_tickets")

    # ── public interface ────────────────────────────────────────────

    def fetch(self, key: str) -> str:
        self.logger.info("fetch issue %s in %s", key, self.repo)
        raw = gh(
            [
                "issue",
                "view",
                key,
                "--repo",
                self.repo,
                "--json",
                "title,body,comments,labels",
            ]
        )
        data = json.loads(raw)
        parts: list[str] = [
            f"# {data['title']}",
            "",
            data.get("body") or "",
        ]
        for c in data.get("comments", []):
            author = c.get("author", {}).get("login", "unknown")
            parts.append("")
            parts.append(f"---\n**{author}**:\n{c['body']}")
        md = "\n".join(parts)
        self.logger.debug("fetch result length: %d chars", len(md))
        return md

    def get_status(self, key: str) -> str:
        self.logger.info("get_status issue %s in %s", key, self.repo)
        raw = gh(["issue", "view", key, "--repo", self.repo, "--json", "labels"])
        data = json.loads(raw)
        for label in data.get("labels", []):
            name = label.get("name", "")
            if name in STATUS_LABELS:
                self.logger.debug("status for %s: %s", key, name)
                return name
        self.logger.debug("status for %s: open (no status label)", key)
        return "open"

    def create_comment(self, key: str, body: str) -> str:
        self.logger.info("create_comment on %s in %s", key, self.repo)
        url = gh(["issue", "comment", key, "--repo", self.repo, "--body", body])
        match = re.search(r"issuecomment-(\d+)", url)
        comment_id = match.group(1) if match else url
        self.logger.debug("created comment %s", comment_id)
        return comment_id

    def update_comment(self, key: str, comment_id: str, body: str) -> None:
        self.logger.info("update_comment %s on %s in %s", comment_id, key, self.repo)
        gh(
            [
                "api",
                f"repos/{self.repo}/issues/comments/{comment_id}",
                "-X",
                "PATCH",
                "-f",
                f"body={body}",
            ]
        )
        self.logger.debug("updated comment %s", comment_id)

    def transition(self, key: str, state: str) -> None:
        self.logger.info("transition %s → %s in %s", key, state, self.repo)
        gh(
            [
                "issue",
                "edit",
                key,
                "--repo",
                self.repo,
                "--add-label",
                state,
            ]
        )
        self.logger.debug("transitioned %s to %s", key, state)

    def trigger_next(self, event_type: str, payload: dict) -> None:
        self.logger.info(
            "trigger_next %s in %s with %s", event_type, self.repo, payload
        )
        body = json.dumps({"event_type": event_type, "client_payload": payload})
        gh(
            [
                "api",
                f"repos/{self.repo}/dispatches",
                "-X",
                "POST",
                "--input",
                "-",
            ],
            input_text=body,
        )
        self.logger.debug("dispatched %s", event_type)
