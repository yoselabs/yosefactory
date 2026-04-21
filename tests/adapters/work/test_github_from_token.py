"""Tests for GitHubWorkAdapter.from_token — App-id verification probe."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from a2sdlc.adapters.work.github import GitHubWorkAdapter


@pytest.mark.unit
class TestFromTokenAppIdProbe:
    def test_accepts_matching_app_id(self) -> None:
        """GET /app returns the expected App → adapter constructs."""
        with patch("a2sdlc.adapters.work.github.Github") as MockGithub:
            gh = MockGithub.return_value
            gh.get_app.return_value = MagicMock(id=12345)
            gh.get_repo.return_value = MagicMock()

            adapter = GitHubWorkAdapter.from_token(
                token="ghs_xxx", repo_name="owner/repo", expected_app_id="12345"
            )
            assert adapter is not None
            gh.get_app.assert_called_once()

    def test_rejects_mismatched_app_id(self) -> None:
        """GET /app returns a different App id → ValueError."""
        with patch("a2sdlc.adapters.work.github.Github") as MockGithub:
            gh = MockGithub.return_value
            gh.get_app.return_value = MagicMock(id=99999)

            with pytest.raises(ValueError, match="app_id=99999"):
                GitHubWorkAdapter.from_token(
                    token="ghs_xxx",
                    repo_name="owner/repo",
                    expected_app_id="12345",
                )

    def test_skips_probe_when_expected_app_id_none(self) -> None:
        """No expected_app_id → no probe, no GET /app call."""
        with patch("a2sdlc.adapters.work.github.Github") as MockGithub:
            gh = MockGithub.return_value
            gh.get_repo.return_value = MagicMock()

            GitHubWorkAdapter.from_token(
                token="ghs_xxx", repo_name="owner/repo", expected_app_id=None
            )
            gh.get_app.assert_not_called()

    def test_wraps_network_errors(self) -> None:
        """GET /app raising → ValueError with helpful guidance."""
        with patch("a2sdlc.adapters.work.github.Github") as MockGithub:
            gh = MockGithub.return_value
            gh.get_app.side_effect = RuntimeError("network down")

            with pytest.raises(ValueError, match="Token verification failed"):
                GitHubWorkAdapter.from_token(
                    token="ghs_xxx",
                    repo_name="owner/repo",
                    expected_app_id="12345",
                )
