from __future__ import annotations

import os

from a2sdlc.adapters.base import CodeAdapter, TicketAdapter


def get_ticket_adapter(name: str, **kwargs) -> TicketAdapter:
    if name == "github-issues":
        from a2sdlc.adapters.github_tickets import GitHubTickets

        return GitHubTickets(repo=kwargs["repo"])
    elif name == "jira":
        from a2sdlc.adapters.jira_tickets import JiraTickets  # ty: ignore[unresolved-import]

        return JiraTickets(
            url=os.environ["JIRA_URL"],
            username=os.environ["JIRA_USERNAME"],
            token=os.environ["JIRA_API_TOKEN"],
            github_repo=kwargs["repo"],
        )
    raise ValueError(f"Unknown ticket adapter: {name}")


def get_code_adapter(name: str, **kwargs) -> CodeAdapter:
    if name == "github":
        from a2sdlc.adapters.github_code import GitHubCode  # ty: ignore[unresolved-import]

        return GitHubCode(repo=kwargs["repo"])
    raise ValueError(f"Unknown code adapter: {name}")
