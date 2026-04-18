"""Factory selects concrete adapters by string name."""

import subprocess
from pathlib import Path

import pytest

from a2sdlc.adapters.factory import (
    build_git_adapter,
    build_review_adapter,
    build_work_adapter,
)
from a2sdlc.adapters.git import LocalBranchGitAdapter
from a2sdlc.adapters.work import LocalFileWorkAdapter
from a2sdlc.adapters.review import LocalNoopReviewAdapter
from a2sdlc.domain.models import StageName


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "README.md").write_text("init")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


def test_build_work_adapter_local_file(tmp_path):
    """GIVEN name='local_file'
    WHEN build_work_adapter is called with full kwargs
    THEN a LocalFileWorkAdapter instance is returned."""
    (tmp_path / ".a2sdlc").mkdir()
    w = build_work_adapter(
        "local_file",
        project_root=tmp_path,
        session_id="sid",
        stage=StageName.SPEC,
        ticket_path=None,
    )
    assert isinstance(w, LocalFileWorkAdapter)


def test_build_review_adapter_local_noop(tmp_path):
    """GIVEN name='local_noop' WHEN build_review_adapter is called THEN LocalNoopReviewAdapter is returned."""
    r = build_review_adapter("local_noop", project_root=tmp_path)
    assert isinstance(r, LocalNoopReviewAdapter)


def test_build_git_adapter_local_branch(tmp_path):
    """GIVEN name='local_branch' WHEN build_git_adapter is called THEN LocalBranchGitAdapter is returned."""
    _init_repo(tmp_path)
    g = build_git_adapter("local_branch", project_root=tmp_path)
    assert isinstance(g, LocalBranchGitAdapter)


def test_build_work_adapter_unknown_raises():
    """GIVEN an unknown work adapter name WHEN build_work_adapter is called THEN ValueError is raised."""
    with pytest.raises(ValueError, match="unknown work adapter"):
        build_work_adapter(
            "nonsense",
            project_root=Path("."),
            session_id="s",
            stage=StageName.SPEC,
            ticket_path=None,
        )


def test_build_review_adapter_unknown_raises(tmp_path):
    with pytest.raises(ValueError, match="unknown review adapter"):
        build_review_adapter("nonsense", project_root=tmp_path)


def test_build_git_adapter_unknown_raises(tmp_path):
    with pytest.raises(ValueError, match="unknown git adapter"):
        build_git_adapter("nonsense", project_root=tmp_path)


def test_build_work_adapter_jira_deferred(tmp_path):
    """GIVEN name='jira' WHEN build_work_adapter is called THEN NotImplementedError signals deferred wiring."""
    with pytest.raises(NotImplementedError, match="jira adapter"):
        build_work_adapter(
            "jira",
            project_root=tmp_path,
            session_id="s",
            stage=StageName.SPEC,
            ticket_path=None,
        )


def test_build_review_adapter_github_deferred(tmp_path):
    """GIVEN name='github' WHEN build_review_adapter is called THEN NotImplementedError signals deferred wiring."""
    with pytest.raises(NotImplementedError, match="github review adapter"):
        build_review_adapter("github", project_root=tmp_path)


def test_build_git_adapter_github_returns_local_git(tmp_path):
    """GIVEN name='github' WHEN build_git_adapter is called THEN the CI-side LocalGitAdapter is returned."""
    from a2sdlc.adapters.git import LocalGitAdapter

    _init_repo(tmp_path)
    g = build_git_adapter("github", project_root=tmp_path)
    assert isinstance(g, LocalGitAdapter)
