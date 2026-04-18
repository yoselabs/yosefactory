"""Behavior tests for local_branch git adapter."""

import subprocess
from pathlib import Path

import pytest

from a2sdlc.adapters.git import LocalBranchGitAdapter


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "README.md").write_text("init")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


def test_setup_branch_creates_branch_without_touching_origin(tmp_path):
    """GIVEN a repo with no `origin` remote
    WHEN setup_branch is called
    THEN the branch is created locally without error."""
    _init_repo(tmp_path)
    adapter = LocalBranchGitAdapter(project_root=tmp_path)

    adapter.setup_branch("a2sdlc/test-session", "main")

    current = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert current == "a2sdlc/test-session"


def test_setup_branch_reuses_existing_branch(tmp_path):
    """GIVEN a session branch already exists
    WHEN setup_branch is called again with the same name
    THEN it checks out the existing branch (no -b)."""
    _init_repo(tmp_path)
    adapter = LocalBranchGitAdapter(project_root=tmp_path)
    adapter.setup_branch("a2sdlc/sid1", "main")
    subprocess.run(["git", "checkout", "main"], cwd=tmp_path, check=True)
    adapter.setup_branch("a2sdlc/sid1", "main")
    current = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert current == "a2sdlc/sid1"


def test_push_is_noop(tmp_path):
    """GIVEN a local branch
    WHEN push() is called
    THEN no error is raised (no network IO)."""
    _init_repo(tmp_path)
    adapter = LocalBranchGitAdapter(project_root=tmp_path)
    adapter.setup_branch("a2sdlc/test", "main")
    adapter.push()  # must not raise


def test_sync_with_base_is_noop(tmp_path):
    """GIVEN a local branch
    WHEN sync_with_base is called
    THEN it returns True and does not touch origin."""
    _init_repo(tmp_path)
    adapter = LocalBranchGitAdapter(project_root=tmp_path)
    adapter.setup_branch("a2sdlc/test", "main")
    assert adapter.sync_with_base("main") is True


def test_setup_branch_raises_blocked_error_on_invalid_base(tmp_path):
    """GIVEN a request to branch from a non-existent base
    WHEN setup_branch is called
    THEN BlockedError is raised with git's stderr message."""
    from a2sdlc.domain.exceptions import BlockedError

    _init_repo(tmp_path)
    adapter = LocalBranchGitAdapter(project_root=tmp_path)
    with pytest.raises(
        BlockedError,
        match="(?i)(unknown|invalid|not a valid|not a commit|pathspec|bad)",
    ):
        adapter.setup_branch("a2sdlc/from-ghost", "nonexistent-base")
