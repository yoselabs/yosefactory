"""Tests for ``a2sdlc scrub-base`` CLI subcommand."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestScrubBaseCommand:
    def test_echoes_scrubbed_when_helper_returns_true(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from a2sdlc.cli.scrub_base import scrub_base_command

        adapter = MagicMock()
        with (
            patch(
                "a2sdlc.adapters.work.github.GitHubWorkAdapter.from_token",
                return_value=adapter,
            ),
            patch(
                "a2sdlc.adapters.work.scrub_base.scrub_base",
                return_value=True,
            ) as helper,
        ):
            scrub_base_command(repo="o/r", token="tok", base="main")

        helper.assert_called_once_with(adapter._repo, "main")
        assert "scrubbed" in capsys.readouterr().out

    def test_echoes_clean_when_helper_returns_false(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from a2sdlc.cli.scrub_base import scrub_base_command

        adapter = MagicMock()
        with (
            patch(
                "a2sdlc.adapters.work.github.GitHubWorkAdapter.from_token",
                return_value=adapter,
            ),
            patch(
                "a2sdlc.adapters.work.scrub_base.scrub_base",
                return_value=False,
            ),
        ):
            scrub_base_command(repo="o/r", token="tok", base="main")

        assert "clean" in capsys.readouterr().out

    def test_missing_repo_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import typer

        from a2sdlc.cli.scrub_base import scrub_base_command

        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        with pytest.raises(typer.BadParameter):
            scrub_base_command(repo=None, token="tok", base="main")

    def test_missing_token_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import typer

        from a2sdlc.cli.scrub_base import scrub_base_command

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with pytest.raises(typer.BadParameter):
            scrub_base_command(repo="o/r", token=None, base="main")
