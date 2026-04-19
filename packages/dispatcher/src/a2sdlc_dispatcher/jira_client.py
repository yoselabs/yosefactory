"""Thin JiraClient wrapping atlassian-python-api.

Centralizes the Jira calls the dispatcher needs: comment, transition,
and "find candidates blocked only by X" query. Returns native Python
types, not atlassian-api wrappers.
"""

from __future__ import annotations

from typing import Any


class JiraClient:
    def __init__(self, raw: Any) -> None:
        # `raw` is an atlassian.Jira instance.
        self._raw = raw

    def add_comment(self, ticket_key: str, body: str) -> None:
        self._raw.issue_add_comment(ticket_key, body)

    def transition(self, ticket_key: str, *, to_status: str) -> None:
        transitions = self._raw.get_issue_transitions(ticket_key)
        for t in transitions:
            if t.get("name") == to_status:
                self._raw.issue_transition(ticket_key, t["id"])
                return
        raise ValueError(
            f"no transition named {to_status!r} from current state of {ticket_key}"
        )

    def find_issues_blocked_only_by(
        self, ticket_key: str, *, project_key: str, blocked_status: str
    ) -> list[str]:
        """Return tickets that have ticket_key as a blocker.

        Uses Jira's linkedIssues() JQL — "blocks" is the outward link type
        whose inward label is "is blocked by". A ticket X that `blocks` Y
        appears in `linkedIssues(X, "blocks")` as Y.

        Caller must verify each candidate's OTHER blockers are also Done
        before transitioning it to Ready.
        """
        jql = (
            f'project = "{project_key}" '
            f'AND status = "{blocked_status}" '
            f'AND issue in linkedIssues("{ticket_key}", "blocks")'
        )
        result = self._raw.jql(jql, fields="key")
        return [issue["key"] for issue in result.get("issues", [])]

    def get_blockers(self, ticket_key: str) -> list[tuple[str, str]]:
        """Return [(key, status_name), ...] for each issue this one is blocked by."""
        issue = self._raw.issue(ticket_key, fields="issuelinks,status")
        out: list[tuple[str, str]] = []
        for link in issue["fields"].get("issuelinks", []):
            ltype = link.get("type", {}).get("inward", "")
            if "blocked by" in ltype.lower():
                other = link.get("inwardIssue") or link.get("outwardIssue")
                if other:
                    out.append((other["key"], other["fields"]["status"]["name"]))
        return out
