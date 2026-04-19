"""Adapter factory — map config adapter names to concrete implementations."""

from __future__ import annotations

from pathlib import Path

from a2sdlc.adapters.git import LocalBranchGitAdapter
from a2sdlc.adapters.work import LocalFileWorkAdapter
from a2sdlc.adapters.review import LocalNoopReviewAdapter
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
        raise NotImplementedError("jira work adapter not wired through factory yet")
    raise ValueError(f"unknown work adapter: {name}")


def build_review_adapter(name: str, *, project_root: Path):
    if name == "local_noop":
        return LocalNoopReviewAdapter(project_root=project_root)
    if name == "github":
        raise NotImplementedError("github review adapter not wired through factory yet")
    raise ValueError(f"unknown review adapter: {name}")


def build_git_adapter(name: str, *, project_root: Path):
    if name == "local_branch":
        return LocalBranchGitAdapter(project_root=project_root)
    if name == "github":
        # CI-side git adapter: LocalGitAdapter with a real remote. Default
        # AdaptersConfig.git value; matches the GitHub Actions dispatch context.
        from a2sdlc.adapters.git import LocalGitAdapter  # noqa: PLC0415

        return LocalGitAdapter(project_root=project_root)
    raise ValueError(f"unknown git adapter: {name}")
