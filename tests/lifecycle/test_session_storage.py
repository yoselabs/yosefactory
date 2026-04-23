"""Tests for SessionStorage Protocol + LocalDiskSessionStorage impl."""

from __future__ import annotations

from pathlib import Path

import pytest

from a2sdlc.lifecycle.session_storage import (
    LocalDiskSessionStorage,
    SessionStorage,
)


@pytest.mark.unit
class TestLocalDiskSessionStorage:
    def test_save_load_round_trip(self, tmp_path: Path) -> None:
        storage = LocalDiskSessionStorage(tmp_path / "sessions")
        storage.save("session-abc", b"hello")
        assert storage.load("session-abc") == b"hello"

    def test_load_absent_returns_none(self, tmp_path: Path) -> None:
        storage = LocalDiskSessionStorage(tmp_path / "sessions")
        assert storage.load("missing") is None

    def test_save_creates_parent_directory(self, tmp_path: Path) -> None:
        storage = LocalDiskSessionStorage(tmp_path / "a" / "b" / "c")
        storage.save("session-1", b"x")
        assert (tmp_path / "a" / "b" / "c" / "session-1").is_file()

    def test_save_overwrites_existing(self, tmp_path: Path) -> None:
        storage = LocalDiskSessionStorage(tmp_path / "sessions")
        storage.save("session-1", b"v1")
        storage.save("session-1", b"v2")
        assert storage.load("session-1") == b"v2"

    def test_purge_removes_file(self, tmp_path: Path) -> None:
        storage = LocalDiskSessionStorage(tmp_path / "sessions")
        storage.save("session-1", b"x")
        storage.purge("session-1")
        assert storage.load("session-1") is None

    def test_purge_missing_is_noop(self, tmp_path: Path) -> None:
        storage = LocalDiskSessionStorage(tmp_path / "sessions")
        storage.purge("never-existed")  # must not raise

    def test_impl_satisfies_protocol(self, tmp_path: Path) -> None:
        # Protocol conformance — impl is assignable to SessionStorage.
        storage: SessionStorage = LocalDiskSessionStorage(tmp_path / "sessions")
        storage.save("s", b"x")
        assert storage.load("s") == b"x"

    def test_docstring_documents_consistency_model(self) -> None:
        # ADR-0005 I8 mirror: each impl documents its consistency model.
        doc = LocalDiskSessionStorage.__doc__
        assert doc is not None
        lowered = doc.lower()
        assert "consistency" in lowered or "concurren" in lowered


class _InMemorySessionStorage:
    """Minimal fake to prove a non-disk impl conforms to the Protocol."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    def save(self, session_id: str, data: bytes) -> None:
        self._data[session_id] = data

    def load(self, session_id: str) -> bytes | None:
        return self._data.get(session_id)

    def purge(self, session_id: str) -> None:
        self._data.pop(session_id, None)


@pytest.mark.unit
class TestProtocolConformance:
    """A fake impl is interchangeable with the real one at the Protocol level."""

    def test_fake_conforms(self) -> None:
        storage: SessionStorage = _InMemorySessionStorage()
        storage.save("s", b"x")
        assert storage.load("s") == b"x"
        storage.purge("s")
        assert storage.load("s") is None
