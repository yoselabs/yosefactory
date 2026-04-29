"""Tests for ``adapters.work.scrub_base.scrub_base``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from github import UnknownObjectException

from a2sdlc.adapters.work.scrub_base import STATE_FILE_PATH, scrub_base


@pytest.mark.unit
class TestScrubBase:
    def test_deletes_file_when_present(self) -> None:
        contents = MagicMock()
        contents.path = STATE_FILE_PATH
        contents.sha = "abc123"
        repo = MagicMock()
        repo.get_contents.return_value = contents

        result = scrub_base(repo, base="main")

        assert result is True
        repo.delete_file.assert_called_once_with(
            path=STATE_FILE_PATH,
            message="chore(a2sdlc): scrub leaked runtime state",
            sha="abc123",
            branch="main",
        )

    def test_returns_false_when_file_absent(self) -> None:
        repo = MagicMock()
        repo.get_contents.side_effect = UnknownObjectException(404, {}, {})

        result = scrub_base(repo, base="main")

        assert result is False
        repo.delete_file.assert_not_called()

    def test_raises_when_path_resolves_to_directory(self) -> None:
        repo = MagicMock()
        repo.get_contents.return_value = [MagicMock(), MagicMock()]

        with pytest.raises(RuntimeError, match="resolved to a directory"):
            scrub_base(repo, base="main")
