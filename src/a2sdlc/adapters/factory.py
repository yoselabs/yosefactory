"""Adapter factory — map config adapter names to concrete implementations."""

from __future__ import annotations

from pathlib import Path

from a2sdlc.adapters.local_branch_git import LocalBranchGitAdapter
from a2sdlc.adapters.local_file_work import LocalFileWorkAdapter
from a2sdlc.adapters.local_noop_review import LocalNoopReviewAdapter
from a2sdlc.domain.models import StageName


def build_work_adapter(
    name: str,
    *,
    project_root: Path,
    session_id: str,
    stage: StageName,
    ticket_path: Path | None,
):
    if name == "local_file":
        return LocalFileWorkAdapter(
            project_root=project_root,
            session_id=session_id,
            stage=stage,
            ticket_path=ticket_path,
        )
    if name == "jira":
        # TODO: Jira adapter construction uses existing GitHubWorkAdapter pattern
        # in cli.py; factory-level wiring deferred until Task 9 refactors cli.py.
        raise NotImplementedError(
            "jira adapter is built directly in cli.py today; "
            "factory wiring arrives when cli.py is refactored"
        )
    raise ValueError(f"unknown work adapter: {name}")


def build_review_adapter(name: str, *, project_root: Path):
    if name == "local_noop":
        return LocalNoopReviewAdapter(project_root=project_root)
    if name == "github":
        raise NotImplementedError(
            "github review adapter is built directly in cli.py today; "
            "factory wiring arrives when cli.py is refactored"
        )
    raise ValueError(f"unknown review adapter: {name}")


def build_git_adapter(name: str, *, project_root: Path):
    if name == "local_branch":
        return LocalBranchGitAdapter(project_root=project_root)
    if name == "github":
        # Historical name for the CI-side git adapter (LocalGitAdapter with remotes).
        from a2sdlc.adapters.git import LocalGitAdapter  # noqa: PLC0415

        return LocalGitAdapter(project_root=project_root)
    raise ValueError(f"unknown git adapter: {name}")
