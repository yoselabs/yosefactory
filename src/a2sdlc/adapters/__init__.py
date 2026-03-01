from __future__ import annotations

from a2sdlc.adapters.base import CodeAdapter, TicketAdapter


def get_ticket_adapter(name: str, **kwargs: str) -> TicketAdapter:
    if name == "github-issues":
        from a2sdlc.adapters.github_tickets import GitHubTickets

        return GitHubTickets(repo=kwargs["repo"])
    raise ValueError(f"Unknown ticket adapter: {name}")


def get_code_adapter(name: str, **kwargs: str) -> CodeAdapter:
    if name == "github":
        from a2sdlc.adapters.github_code import GitHubCode

        return GitHubCode(repo=kwargs["repo"])
    raise ValueError(f"Unknown code adapter: {name}")
