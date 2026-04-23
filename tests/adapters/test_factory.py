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


def test_build_work_adapter_github_issue_uses_env_token(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    """github_issue arm pulls GITHUB_TOKEN + GITHUB_REPOSITORY from env."""
    captured: dict[str, str] = {}

    def _fake_from_token(cls, token, repo_name, trigger_mention="@a2sdlc"):
        captured["token"] = token
        captured["repo_name"] = repo_name
        return object()

    from a2sdlc.adapters.work import GitHubWorkAdapter

    monkeypatch.setattr(GitHubWorkAdapter, "from_token", classmethod(_fake_from_token))
    build_work_adapter(
        "github_issue",
        project_root=tmp_path,
        session_id="s",
        stage=StageName.SPEC,
        env={"GITHUB_TOKEN": "tok-1", "GITHUB_REPOSITORY": "o/r"},
    )
    assert captured == {"token": "tok-1", "repo_name": "o/r"}


def test_build_work_adapter_github_issue_falls_back_to_gh_token(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    captured: dict[str, str] = {}

    def _fake_from_token(cls, token, repo_name, trigger_mention="@a2sdlc"):
        captured["token"] = token
        return object()

    from a2sdlc.adapters.work import GitHubWorkAdapter

    monkeypatch.setattr(GitHubWorkAdapter, "from_token", classmethod(_fake_from_token))
    build_work_adapter(
        "github_issue",
        project_root=tmp_path,
        session_id="s",
        stage=StageName.SPEC,
        env={"GH_TOKEN": "fallback-tok", "GITHUB_REPOSITORY": "o/r"},
    )
    assert captured["token"] == "fallback-tok"


def test_build_review_adapter_github(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """github review arm constructs a Github client + wraps it in GitHubReviewAdapter."""
    from a2sdlc.adapters.review import GitHubReviewAdapter

    captured: dict[str, str] = {}

    class _FakeRepo:
        pass

    class _FakeGithub:
        def __init__(self, token):
            captured["token"] = token

        def get_repo(self, name):
            captured["repo_name"] = name
            return _FakeRepo()

    # The factory does a local `from github import Github`. Patch the
    # symbol on the adapters.review module that the adapter imports, and
    # replace the factory's lazy import by patching sys.modules.
    import sys
    import types

    fake_module = types.ModuleType("github")
    setattr(fake_module, "Github", _FakeGithub)  # noqa: B010
    monkeypatch.setitem(sys.modules, "github", fake_module)

    r = build_review_adapter(
        "github",
        project_root=tmp_path,
        env={"GITHUB_TOKEN": "tok-r", "GITHUB_REPOSITORY": "o/r"},
    )
    assert isinstance(r, GitHubReviewAdapter)
    assert captured == {"token": "tok-r", "repo_name": "o/r"}


def test_build_work_adapter_workflow_input(tmp_path):
    """GIVEN name='workflow_input' THEN a WorkflowInputReader is returned."""
    from a2sdlc.adapters.work.workflow_input import WorkflowInputReader

    w = build_work_adapter(
        "workflow_input",
        project_root=tmp_path,
        session_id="s",
        stage=StageName.SPEC,
    )
    assert isinstance(w, WorkflowInputReader)


def test_build_git_adapter_local_alias_returns_local_git(tmp_path):
    """GIVEN name='local' or 'github' THEN LocalGitAdapter is returned (aliased)."""
    from a2sdlc.adapters.git import LocalGitAdapter

    _init_repo(tmp_path)
    g_canonical = build_git_adapter("local", project_root=tmp_path)
    g_legacy = build_git_adapter("github", project_root=tmp_path)
    assert isinstance(g_canonical, LocalGitAdapter)
    assert isinstance(g_legacy, LocalGitAdapter)
