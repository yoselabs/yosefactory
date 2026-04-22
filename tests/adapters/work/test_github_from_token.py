"""Unit tests for GitHubWorkAdapter.from_token installation-token probe.

The probe is a raw `requests` call — mocked here. Replayed integration
coverage lives under `tests/integration/adapters/` with recorded
cassettes (see P2.6b + the reflect signal on auth-mode bugs).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from a2sdlc.adapters.work.github import GitHubWorkAdapter


@pytest.mark.unit
class TestFromTokenProbe:
    def test_rejects_non_installation_token(self) -> None:
        """GHA default `GITHUB_TOKEN` can't hit `/installation/repositories`."""
        fake_response = MagicMock(status_code=403)

        with (
            patch(
                "a2sdlc.adapters.work.github.requests.get",
                return_value=fake_response,
            ),
            patch("a2sdlc.adapters.work.github.Github"),
        ):
            with pytest.raises(ValueError, match="create-github-app-token"):
                GitHubWorkAdapter.from_token("ghs_not-an-app-token", "o/r")

    def test_accepts_installation_token(self) -> None:
        """2xx response → probe passes, factory constructs normally."""
        fake_response = MagicMock(status_code=200)
        fake_gh = MagicMock()
        fake_gh.get_repo.return_value = MagicMock(name="repo")

        with (
            patch(
                "a2sdlc.adapters.work.github.requests.get",
                return_value=fake_response,
            ),
            patch(
                "a2sdlc.adapters.work.github.Github", return_value=fake_gh
            ) as mock_github,
        ):
            adapter = GitHubWorkAdapter.from_token("ghs_valid-install-token", "o/r")

        assert adapter is not None
        mock_github.assert_called_once_with("ghs_valid-install-token")
        fake_gh.get_repo.assert_called_once_with("o/r")

    def test_network_error_does_not_block_construction(self) -> None:
        """Transient network failures let PyGithub's own retry path handle it —
        the probe is a correctness gate, not a liveness check.
        """
        import requests as _requests  # noqa: PLC0415

        fake_gh = MagicMock()
        fake_gh.get_repo.return_value = MagicMock(name="repo")

        with (
            patch(
                "a2sdlc.adapters.work.github.requests.get",
                side_effect=_requests.ConnectionError("boom"),
            ),
            patch("a2sdlc.adapters.work.github.Github", return_value=fake_gh),
        ):
            adapter = GitHubWorkAdapter.from_token("ghs_anything", "o/r")

        assert adapter is not None

    def test_401_on_expired_token(self) -> None:
        """Expired / revoked installation token surfaces the same guidance."""
        fake_response = MagicMock(status_code=401)

        with (
            patch(
                "a2sdlc.adapters.work.github.requests.get",
                return_value=fake_response,
            ),
            patch("a2sdlc.adapters.work.github.Github"),
        ):
            with pytest.raises(ValueError, match="401"):
                GitHubWorkAdapter.from_token("ghs_expired", "o/r")
