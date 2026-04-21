"""Tests for StateStorage backends."""

from __future__ import annotations

import pytest

from a2sdlc.lifecycle.state_storage import GitFileStateStorage
from tests.fakes import FakeGitAdapter


@pytest.mark.unit
class TestGitFileStateStorage:
    def test_read_delegates_to_git_read_state(self) -> None:
        git = FakeGitAdapter(state_json='{"stage":"spec"}')
        storage = GitFileStateStorage(git)
        assert storage.read("PROJ-1") == '{"stage":"spec"}'

    def test_read_returns_none_when_absent(self) -> None:
        git = FakeGitAdapter(state_json=None)
        storage = GitFileStateStorage(git)
        assert storage.read("PROJ-1") is None

    def test_write_delegates_to_git_write_state(self) -> None:
        git = FakeGitAdapter()
        storage = GitFileStateStorage(git)
        storage.write("PROJ-1", '{"stage":"review"}')
        assert git.written_state == ['{"stage":"review"}']

    def test_key_is_ignored_for_file_backend(self) -> None:
        """File backend scopes by checked-out branch; key is a no-op here."""
        git = FakeGitAdapter(state_json='{"stage":"merge"}')
        storage = GitFileStateStorage(git)
        # Two different keys both return the same underlying file.
        assert storage.read("A-1") == storage.read("B-2")
