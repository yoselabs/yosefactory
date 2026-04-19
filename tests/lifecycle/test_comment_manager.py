"""Tests for CommentManager — comment lifecycle enforcement."""

from __future__ import annotations

import pytest

from a2sdlc.lifecycle.comment import CommentManager
from a2sdlc.domain.exceptions import RetryableError
from tests.fakes import FakeWorkAdapter


# -- Fixtures ----------------------------------------------------------


@pytest.fixture()
def adapter() -> FakeWorkAdapter:
    return FakeWorkAdapter(event=None, ticket_body="", labels=None)


@pytest.fixture()
def manager(adapter: FakeWorkAdapter) -> CommentManager:
    return CommentManager(work=adapter, ticket_key="PROJ-1")


# -- comment_id property -----------------------------------------------


def test_comment_id_is_none_before_start(manager: CommentManager) -> None:
    assert manager.comment_id is None


def test_comment_id_is_set_after_start(
    manager: CommentManager, adapter: FakeWorkAdapter
) -> None:
    manager.start("spec")
    assert manager.comment_id == "comment-1"


def test_comment_id_remains_after_finalize(
    manager: CommentManager, adapter: FakeWorkAdapter
) -> None:
    manager.start("spec")
    manager.finalize("done")
    assert manager.comment_id == "comment-1"


# -- start -------------------------------------------------------------


def test_start_calls_begin_comment(
    manager: CommentManager, adapter: FakeWorkAdapter
) -> None:
    manager.start("spec")
    assert len(adapter.created_comments) == 1


def test_start_twice_without_finalize_raises(manager: CommentManager) -> None:
    manager.start("spec")
    with pytest.raises(RuntimeError):
        manager.start("implement")


def test_start_after_finalize_succeeds(
    manager: CommentManager, adapter: FakeWorkAdapter
) -> None:
    manager.start("spec")
    manager.finalize("done")
    manager.start("implement")
    assert len(adapter.created_comments) == 2
    assert manager.comment_id == "comment-2"


# -- update ------------------------------------------------------------


def test_update_forwards_body_with_correct_comment_id(
    manager: CommentManager, adapter: FakeWorkAdapter
) -> None:
    manager.start("spec")
    manager.update("progress body")
    assert adapter.progress_updates == [("comment-1", "progress body")]


def test_update_before_start_is_no_op(
    manager: CommentManager, adapter: FakeWorkAdapter
) -> None:
    manager.update("nothing")
    assert adapter.progress_updates == []


# -- finalize ----------------------------------------------------------


def test_finalize_forwards_body_with_correct_comment_id(
    manager: CommentManager, adapter: FakeWorkAdapter
) -> None:
    manager.start("spec")
    manager.finalize("final body")
    assert adapter.finalized_comments == [("comment-1", "final body")]


def test_double_finalize_is_idempotent(
    manager: CommentManager, adapter: FakeWorkAdapter
) -> None:
    manager.start("spec")
    manager.finalize("final body")
    manager.finalize("final body again")
    assert len(adapter.finalized_comments) == 1


# -- retry on finalize -------------------------------------------------


class _FlakyFinalizeAdapter(FakeWorkAdapter):
    """Raises RetryableError on the first finalize_comment call."""

    def __init__(self) -> None:
        super().__init__(event=None, ticket_body="", labels=None)
        self._first_finalize = True

    def finalize_comment(self, comment_id: str, body: str) -> None:
        if self._first_finalize:
            self._first_finalize = False
            raise RetryableError("flaky network")
        super().finalize_comment(comment_id, body)


def test_finalize_retries_on_retryable_error() -> None:
    adapter = _FlakyFinalizeAdapter()
    manager = CommentManager(work=adapter, ticket_key="PROJ-2")
    manager.start("spec")
    manager.finalize("final")
    assert adapter.finalized_comments == [("comment-1", "final")]
