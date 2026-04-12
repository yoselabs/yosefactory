"""Comment lifecycle contract tests for WorkAdapter.

These tests verify the contract that all WorkAdapter implementations must honour.
They run against FakeWorkAdapter as a reference implementation.
"""

from __future__ import annotations

import pytest

from a2sdlc.models import StageName
from tests.fakes_v2 import FakeWorkAdapter


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def adapter() -> FakeWorkAdapter:
    return FakeWorkAdapter(event=None, ticket_body="", labels=None)


# ── begin_comment ─────────────────────────────────────────────────────


def test_begin_comment_returns_unique_ids(adapter: FakeWorkAdapter) -> None:
    id1 = adapter.begin_comment("PROJ-1")
    id2 = adapter.begin_comment("PROJ-1")
    id3 = adapter.begin_comment("PROJ-2")
    assert id1 != id2
    assert id1 != id3
    assert id2 != id3


def test_begin_comment_ids_are_strings(adapter: FakeWorkAdapter) -> None:
    comment_id = adapter.begin_comment("PROJ-1")
    assert isinstance(comment_id, str)
    assert len(comment_id) > 0


def test_begin_comment_increments_sequentially(adapter: FakeWorkAdapter) -> None:
    id1 = adapter.begin_comment("PROJ-1")
    id2 = adapter.begin_comment("PROJ-1")
    # IDs follow a predictable pattern: comment-1, comment-2, ...
    assert id1 == "comment-1"
    assert id2 == "comment-2"


def test_begin_comment_tracks_created_count(adapter: FakeWorkAdapter) -> None:
    adapter.begin_comment("PROJ-1")
    adapter.begin_comment("PROJ-2")
    adapter.begin_comment("PROJ-3")
    assert len(adapter.created_comments) == 3


def test_begin_comment_records_all_ids(adapter: FakeWorkAdapter) -> None:
    id1 = adapter.begin_comment("PROJ-1")
    id2 = adapter.begin_comment("PROJ-2")
    assert id1 in adapter.created_comments
    assert id2 in adapter.created_comments


# ── update_progress ────────────────────────────────────────────────────


def test_update_progress_records_comment_id_and_body(adapter: FakeWorkAdapter) -> None:
    comment_id = adapter.begin_comment("PROJ-1")
    adapter.update_progress(comment_id, "Working on it...")
    assert (comment_id, "Working on it...") in adapter.progress_updates


def test_update_progress_records_multiple_updates(adapter: FakeWorkAdapter) -> None:
    comment_id = adapter.begin_comment("PROJ-1")
    adapter.update_progress(comment_id, "Step 1 done")
    adapter.update_progress(comment_id, "Step 2 done")
    assert len(adapter.progress_updates) == 2
    assert adapter.progress_updates[0] == (comment_id, "Step 1 done")
    assert adapter.progress_updates[1] == (comment_id, "Step 2 done")


def test_update_progress_supports_multiple_comments(adapter: FakeWorkAdapter) -> None:
    id1 = adapter.begin_comment("PROJ-1")
    id2 = adapter.begin_comment("PROJ-2")
    adapter.update_progress(id1, "First comment update")
    adapter.update_progress(id2, "Second comment update")
    assert (id1, "First comment update") in adapter.progress_updates
    assert (id2, "Second comment update") in adapter.progress_updates


# ── finalize_comment ──────────────────────────────────────────────────


def test_finalize_comment_records_comment_id_and_body(adapter: FakeWorkAdapter) -> None:
    comment_id = adapter.begin_comment("PROJ-1")
    adapter.finalize_comment(comment_id, "Done!")
    assert (comment_id, "Done!") in adapter.finalized_comments


def test_finalize_comment_records_correct_pairs(adapter: FakeWorkAdapter) -> None:
    id1 = adapter.begin_comment("PROJ-1")
    id2 = adapter.begin_comment("PROJ-2")
    adapter.finalize_comment(id1, "Result 1")
    adapter.finalize_comment(id2, "Result 2")
    assert adapter.finalized_comments[0] == (id1, "Result 1")
    assert adapter.finalized_comments[1] == (id2, "Result 2")


def test_finalize_does_not_affect_progress_updates(adapter: FakeWorkAdapter) -> None:
    comment_id = adapter.begin_comment("PROJ-1")
    adapter.update_progress(comment_id, "In progress")
    adapter.finalize_comment(comment_id, "Done")
    assert len(adapter.progress_updates) == 1
    assert len(adapter.finalized_comments) == 1


# ── total comments created matches begin_comment calls ────────────────


def test_created_comments_count_matches_begin_calls(adapter: FakeWorkAdapter) -> None:
    for i in range(5):
        adapter.begin_comment(f"PROJ-{i}")
    assert len(adapter.created_comments) == 5


def test_created_comments_is_empty_initially(adapter: FakeWorkAdapter) -> None:
    assert adapter.created_comments == []
    assert adapter.progress_updates == []
    assert adapter.finalized_comments == []


# ── format_branch ─────────────────────────────────────────────────────


def test_format_branch_returns_agent_prefix(adapter: FakeWorkAdapter) -> None:
    result = adapter.format_branch("PROJ-123")
    assert result == "agent/PROJ-123"


def test_format_branch_works_for_various_keys(adapter: FakeWorkAdapter) -> None:
    assert adapter.format_branch("PROJ-1") == "agent/PROJ-1"
    assert adapter.format_branch("ABC-9999") == "agent/ABC-9999"
    assert adapter.format_branch("42") == "agent/42"


# ── label_history ──────────────────────────────────────────────────────


def test_set_stage_label_records_key_and_label(adapter: FakeWorkAdapter) -> None:
    adapter.set_stage_label("PROJ-1", StageName.IMPLEMENT)
    assert ("PROJ-1", "stage:implement") in adapter.label_history


def test_set_stage_label_records_multiple_calls(adapter: FakeWorkAdapter) -> None:
    adapter.set_stage_label("PROJ-1", StageName.SPEC)
    adapter.set_stage_label("PROJ-1", StageName.IMPLEMENT)
    assert len(adapter.label_history) == 2


# ── blocked ───────────────────────────────────────────────────────────


def test_set_blocked_records_key_and_reason(adapter: FakeWorkAdapter) -> None:
    adapter.set_blocked("PROJ-1", "conflict on branch")
    assert ("PROJ-1", "conflict on branch") in adapter.blocked


def test_set_blocked_records_multiple(adapter: FakeWorkAdapter) -> None:
    adapter.set_blocked("PROJ-1", "reason A")
    adapter.set_blocked("PROJ-2", "reason B")
    assert len(adapter.blocked) == 2


# ── parse_event raises SkipEvent when no event configured ────────────


def test_parse_event_raises_skip_when_no_event() -> None:
    from a2sdlc.exceptions import SkipEvent

    adapter = FakeWorkAdapter(event=None, ticket_body="", labels=None)
    with pytest.raises(SkipEvent):
        adapter.parse_event()


def test_parse_event_returns_event_when_configured() -> None:
    from a2sdlc.adapters.work import PipelineEvent
    from a2sdlc.models import StageName

    event = PipelineEvent(key="PROJ-1", stage=StageName.SPEC)
    adapter = FakeWorkAdapter(event=event, ticket_body="", labels=None)
    result = adapter.parse_event()
    assert result == event
