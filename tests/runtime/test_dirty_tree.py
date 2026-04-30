"""Dirty-tree check. Spec CLI surface step 4."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from a2sdlc.runtime.dirty_tree import (
    DirtyTreeError,
    ensure_clean_tree,
    ensure_base_not_protected,
    BaseProtectedError,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _seed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "x@y.z")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("hello\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_clean_tree_passes(tmp_path):
    repo = _seed_repo(tmp_path)
    ensure_clean_tree(repo)


def test_modified_tracked_file_fails(tmp_path):
    repo = _seed_repo(tmp_path)
    (repo / "README.md").write_text("changed\n")
    with pytest.raises(DirtyTreeError):
        ensure_clean_tree(repo)


def test_untracked_outside_a2sdlc_is_tolerated(tmp_path):
    repo = _seed_repo(tmp_path)
    (repo / "scratch.txt").write_text("note\n")
    ensure_clean_tree(repo)


def test_untracked_inside_a2sdlc_fails(tmp_path):
    repo = _seed_repo(tmp_path)
    (repo / ".a2sdlc").mkdir()
    (repo / ".a2sdlc" / "state.json").write_text("{}\n")
    with pytest.raises(DirtyTreeError):
        ensure_clean_tree(repo)


def test_empty_porcelain_lines_skipped(tmp_path, monkeypatch):
    repo = _seed_repo(tmp_path)

    # Simulate `git status --porcelain` returning a stray blank line.
    real_run = subprocess.run

    def fake_run(cmd, *a, **kw):
        result = real_run(cmd, *a, **kw)
        if cmd[:3] == ["git", "status", "--porcelain"]:
            result.stdout = result.stdout + "\n"
        return result

    monkeypatch.setattr(subprocess, "run", fake_run)
    ensure_clean_tree(repo)


def test_protected_base_blocks(tmp_path):
    with pytest.raises(BaseProtectedError):
        ensure_base_not_protected("main", protected={"main", "master"}, allow=False)


def test_protected_base_allowed_with_flag(tmp_path):
    ensure_base_not_protected("main", protected={"main", "master"}, allow=True)
