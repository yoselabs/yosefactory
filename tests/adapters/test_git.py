"""Tests for LocalGitAdapter — mock gitpython."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from a2sdlc.adapters.git import LocalGitAdapter
from a2sdlc.domain.exceptions import BlockedError


@pytest.mark.unit
class TestSetupBranch:
    def test_creates_new_branch(self, tmp_path: Path) -> None:
        with patch("a2sdlc.adapters.git.Repo") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.heads = []
            mock_repo.git = MagicMock()

            adapter = LocalGitAdapter(tmp_path)
            branch = adapter.setup_branch("agent/15", "main")

        assert branch == "agent/15"
        mock_repo.git.checkout.assert_called()

    def test_checks_out_existing_branch(self, tmp_path: Path) -> None:
        with patch("a2sdlc.adapters.git.Repo") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_head = MagicMock()
            mock_head.name = "agent/15"
            mock_repo.heads = [mock_head]
            mock_repo.git = MagicMock()

            adapter = LocalGitAdapter(tmp_path)
            branch = adapter.setup_branch("agent/15", "main")

        assert branch == "agent/15"

    def test_conflict_raises_blocked(self, tmp_path: Path) -> None:
        with patch("a2sdlc.adapters.git.Repo") as MockRepo:
            from git.exc import GitCommandError

            mock_repo = MockRepo.return_value
            mock_repo.heads = []
            mock_repo.git = MagicMock()
            mock_repo.git.merge.side_effect = GitCommandError("merge", "conflict")

            adapter = LocalGitAdapter(tmp_path)
            with pytest.raises(BlockedError, match="conflict"):
                adapter.setup_branch("agent/15", "main")


@pytest.mark.unit
class TestSyncWithBase:
    def test_success(self, tmp_path: Path) -> None:
        with patch("a2sdlc.adapters.git.Repo") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.git = MagicMock()
            adapter = LocalGitAdapter(tmp_path)
            assert adapter.sync_with_base("main") is True

    def test_conflict_returns_false(self, tmp_path: Path) -> None:
        with patch("a2sdlc.adapters.git.Repo") as MockRepo:
            from git.exc import GitCommandError

            mock_repo = MockRepo.return_value
            mock_repo.git = MagicMock()
            mock_repo.git.merge.side_effect = GitCommandError("merge", "conflict")
            adapter = LocalGitAdapter(tmp_path)
            assert adapter.sync_with_base("main") is False


@pytest.mark.unit
class TestCommitArtifacts:
    def test_commits_specified_paths(self, tmp_path: Path) -> None:
        with patch("a2sdlc.adapters.git.Repo") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.git = MagicMock()
            mock_repo.is_dirty.return_value = True

            adapter = LocalGitAdapter(tmp_path)
            result = adapter.commit_artifacts("chore: save", [".a2sdlc/state.json"])

        assert result is True
        mock_repo.git.add.assert_called_once_with(".a2sdlc/state.json")
        mock_repo.git.commit.assert_called_once()

    def test_nothing_to_commit(self, tmp_path: Path) -> None:
        with patch("a2sdlc.adapters.git.Repo") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.git = MagicMock()
            mock_repo.is_dirty.return_value = False

            adapter = LocalGitAdapter(tmp_path)
            result = adapter.commit_artifacts("chore: save", [".a2sdlc/state.json"])

        assert result is False
        mock_repo.git.commit.assert_not_called()


@pytest.mark.unit
class TestPush:
    def test_pushes_current_branch(self, tmp_path: Path) -> None:
        with patch("a2sdlc.adapters.git.Repo") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.git = MagicMock()
            type(mock_repo.active_branch).name = PropertyMock(return_value="agent/15")

            adapter = LocalGitAdapter(tmp_path)
            adapter.push()

        mock_repo.git.push.assert_called_once_with("origin", "agent/15")


@pytest.mark.unit
class TestReadWriteState:
    def test_read_state_exists(self, tmp_path: Path) -> None:
        state_path = tmp_path / ".a2sdlc" / "state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text('{"stage":"spec"}')

        with patch("a2sdlc.adapters.git.Repo"):
            adapter = LocalGitAdapter(tmp_path)
            assert adapter.read_state() == '{"stage":"spec"}'

    def test_read_state_missing(self, tmp_path: Path) -> None:
        with patch("a2sdlc.adapters.git.Repo"):
            adapter = LocalGitAdapter(tmp_path)
            assert adapter.read_state() is None

    def test_write_state(self, tmp_path: Path) -> None:
        with patch("a2sdlc.adapters.git.Repo"):
            adapter = LocalGitAdapter(tmp_path)
            adapter.write_state('{"stage":"implement"}')

        state_path = tmp_path / ".a2sdlc" / "state.json"
        assert state_path.exists()
        assert "implement" in state_path.read_text()
