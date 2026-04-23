"""Adapter factory — map composition-profile slot names to concrete adapters.

Central place where a ``CompositionProfile`` slot (e.g. ``work="github_issue"``)
resolves to a constructed adapter. Called from
``assembly.composition.build_adapters`` in P6 step 4 onward; today also
called directly by ``cli/run_stage.py`` (migrated in P6 step 6).

Credential resolution happens at this layer — factories accept an
``env`` mapping and pull out the tokens they need (``GITHUB_TOKEN``,
``GITHUB_REPOSITORY``, etc.). This keeps credential handling at the
adapter-factory boundary; callers just pass ``os.environ``.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from a2sdlc.adapters.git import LocalBranchGitAdapter, LocalGitAdapter
from a2sdlc.adapters.review import GitHubReviewAdapter, LocalNoopReviewAdapter
from a2sdlc.adapters.work import GitHubWorkAdapter, LocalFileWorkAdapter
from a2sdlc.adapters.work.workflow_input import WorkflowInputReader
from a2sdlc.domain.models import StageName


def build_work_adapter(
    name: str,
    *,
    project_root: Path,
    session_id: str,
    stage: StageName,
    ticket_path: Path | None = None,
    env: Mapping[str, str] | None = None,
):
    """Return the work adapter named ``name``.

    - ``local_file`` — ``LocalFileWorkAdapter`` (file-backed tickets).
    - ``github_issue`` — ``GitHubWorkAdapter.from_token`` (CI GH-native).
      Requires ``GITHUB_TOKEN``/``GH_TOKEN`` + ``GITHUB_REPOSITORY`` in env.
    - ``workflow_input`` — ``WorkflowInputReader`` (dispatcher-driven).
      Reads ``TICKET_KEY`` + ``TICKET_BODY`` etc. from env at call time.
    """
    if name == "local_file":
        return LocalFileWorkAdapter(
            project_root=project_root,
            session_id=session_id,
            stage=stage,
            ticket_path=ticket_path,
        )
    if name == "github_issue":
        env = env or {}
        token = env.get("GITHUB_TOKEN") or env.get("GH_TOKEN") or ""
        repo_name = env.get("GITHUB_REPOSITORY", "")
        return GitHubWorkAdapter.from_token(token, repo_name)
    if name == "workflow_input":
        return WorkflowInputReader()
    raise ValueError(f"unknown work adapter: {name}")


def build_review_adapter(
    name: str,
    *,
    project_root: Path,
    env: Mapping[str, str] | None = None,
):
    """Return the review adapter named ``name``.

    - ``local_noop`` — ``LocalNoopReviewAdapter`` (no-op, for tests / local).
    - ``github`` — ``GitHubReviewAdapter`` around a PyGithub repo. Reads
      ``GITHUB_TOKEN``/``GH_TOKEN`` + ``GITHUB_REPOSITORY`` from env.
    """
    if name == "local_noop":
        return LocalNoopReviewAdapter(project_root=project_root)
    if name == "github":
        from github import Github  # noqa: PLC0415

        env = env or {}
        token = env.get("GITHUB_TOKEN") or env.get("GH_TOKEN") or ""
        repo_name = env.get("GITHUB_REPOSITORY", "")
        return GitHubReviewAdapter(Github(token).get_repo(repo_name))
    raise ValueError(f"unknown review adapter: {name}")


def build_git_adapter(name: str, *, project_root: Path):
    """Return the git adapter named ``name``.

    - ``local_branch`` — ``LocalBranchGitAdapter`` (scratch-branch worktree).
    - ``local`` — ``LocalGitAdapter`` against the checked-out working tree.
    - ``github`` — legacy alias for ``local`` (P6 canonical name is ``local``;
      both resolve to ``LocalGitAdapter`` so existing user configs keep
      working).
    """
    if name == "local_branch":
        return LocalBranchGitAdapter(project_root=project_root)
    if name in {"local", "github"}:
        return LocalGitAdapter(project_root=project_root)
    raise ValueError(f"unknown git adapter: {name}")
