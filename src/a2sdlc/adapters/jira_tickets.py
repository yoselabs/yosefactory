"""JIRA adapter — fetch, comment, transition via python-jira."""

from __future__ import annotations

import json
import logging
import subprocess

from jira import JIRA

from a2sdlc.adapters.base import TicketAdapter


class JiraTickets(TicketAdapter):
    """TicketAdapter backed by JIRA via the ``python-jira`` library."""

    def __init__(self, url: str, username: str, token: str, github_repo: str) -> None:
        self.jira = JIRA(server=url, basic_auth=(username, token))
        self.github_repo = github_repo
        self.logger = logging.getLogger("a2sdlc.adapters.jira_tickets")

    # ── public interface ────────────────────────────────────────────

    def fetch(self, key: str) -> str:
        self.logger.info("fetch issue %s", key)
        issue = self.jira.issue(key)
        parts: list[str] = [
            f"# {issue.fields.summary}",
            "",
            issue.fields.description or "",
        ]
        for c in self.jira.comments(issue):
            author = c.author.displayName
            parts.append("")
            parts.append(f"---\n**{author}**:\n{c.body}")
        md = "\n".join(parts)
        self.logger.debug("fetch result length: %d chars", len(md))
        return md

    def get_status(self, key: str) -> str:
        self.logger.info("get_status issue %s", key)
        status = self.jira.issue(key).fields.status.name
        self.logger.debug("status for %s: %s", key, status)
        return status

    def create_comment(self, key: str, body: str) -> str:
        self.logger.info("create_comment on %s", key)
        comment = self.jira.add_comment(key, body)
        comment_id = str(comment.id)
        self.logger.debug("created comment %s", comment_id)
        return comment_id

    def update_comment(self, key: str, comment_id: str, body: str) -> None:
        self.logger.info("update_comment %s on %s", comment_id, key)
        self.jira.comment(key, comment_id).update(body=body)
        self.logger.debug("updated comment %s", comment_id)

    def transition(self, key: str, state: str) -> None:
        self.logger.info("transition %s → %s", key, state)
        transitions = self.jira.transitions(key)
        for t in transitions:
            if t["name"].lower() == state.lower():
                self.jira.transition_issue(key, t["id"])
                self.logger.debug("transitioned %s to %s", key, state)
                return
        # No matching transition — fall back to label
        self.logger.debug("no transition %r found for %s, adding as label", state, key)
        issue = self.jira.issue(key)
        current = issue.fields.labels or []
        if state not in current:
            issue.update(fields={"labels": current + [state]})
        self.logger.debug("labelled %s with %s", key, state)

    def trigger_next(self, event_type: str, payload: dict) -> None:
        self.logger.info(
            "trigger_next %s in %s with %s", event_type, self.github_repo, payload
        )
        body = json.dumps({"event_type": event_type, "client_payload": payload})
        subprocess.run(
            [
                "gh",
                "api",
                f"repos/{self.github_repo}/dispatches",
                "-X",
                "POST",
                "--input",
                "-",
            ],
            input=body,
            text=True,
            check=True,
        )
        self.logger.debug("dispatched %s", event_type)
