"""Tests for a2sdlc exception types."""

from __future__ import annotations

import pytest

from a2sdlc.exceptions import BlockedError, SkipEvent


@pytest.mark.unit
class TestSkipEvent:
    def test_stores_reason(self) -> None:
        exc = SkipEvent("label 'bug' is not a stage label")
        assert exc.reason == "label 'bug' is not a stage label"
        assert "bug" in str(exc)

    def test_is_exception(self) -> None:
        with pytest.raises(SkipEvent):
            raise SkipEvent("test")


@pytest.mark.unit
class TestBlockedError:
    def test_stores_reason(self) -> None:
        exc = BlockedError("merge conflict with main")
        assert exc.reason == "merge conflict with main"
        assert "conflict" in str(exc)

    def test_is_exception(self) -> None:
        with pytest.raises(BlockedError):
            raise BlockedError("test")
