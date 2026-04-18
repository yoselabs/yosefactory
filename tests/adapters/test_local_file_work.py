"""Behavior tests for local_file_work adapter."""

import json
import time
from datetime import datetime, timezone

from a2sdlc.adapters.local_file_work import LocalFileWorkAdapter
from a2sdlc.domain.models import StageName


def _mk_a2sdlc(root):
    (root / ".a2sdlc").mkdir(exist_ok=True)


def test_parse_event_no_feedback_no_pr_returns_active_stage(tmp_path):
    """GIVEN no feedback.json and no pr.json
    WHEN parse_event is called with stage=SPEC
    THEN trigger_stage=SPEC, is_feedback=False, pr_number=None, key=session_id."""
    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.SPEC,
        ticket_path=None,
    )

    event = adapter.parse_event()

    assert event.key == "sid-1"
    assert event.trigger_stage == StageName.SPEC
    assert event.is_feedback is False
    assert event.pr_number is None


def test_parse_event_pr_json_present_sets_pr_number(tmp_path):
    """GIVEN pr.json with pr_number=1
    WHEN parse_event is called
    THEN event.pr_number == 1."""
    _mk_a2sdlc(tmp_path)
    (tmp_path / ".a2sdlc" / "pr.json").write_text(json.dumps({"pr_number": 1}))

    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.IMPLEMENT,
        ticket_path=None,
    )

    event = adapter.parse_event()

    assert event.pr_number == 1


def test_parse_event_unconsumed_feedback_marks_is_feedback(tmp_path):
    """GIVEN feedback.json with consumed=false
    WHEN parse_event is called
    THEN is_feedback=True and trigger_stage=None."""
    _mk_a2sdlc(tmp_path)
    (tmp_path / ".a2sdlc" / "feedback.json").write_text(
        json.dumps({"consumed": False, "body": "fix"})
    )

    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.IMPLEMENT,
        ticket_path=None,
    )

    event = adapter.parse_event()

    assert event.is_feedback is True
    assert event.trigger_stage is None


def test_parse_event_consumed_feedback_falls_back_to_active(tmp_path):
    """GIVEN feedback.json with consumed=true
    WHEN parse_event is called
    THEN is_feedback=False and trigger_stage=<active>."""
    _mk_a2sdlc(tmp_path)
    (tmp_path / ".a2sdlc" / "feedback.json").write_text(
        json.dumps({"consumed": True, "body": "old"})
    )

    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.REVIEW,
        ticket_path=None,
    )

    event = adapter.parse_event()

    assert event.is_feedback is False
    assert event.trigger_stage == StageName.REVIEW


def test_get_ticket_returns_copied_content(tmp_path):
    """GIVEN ticket_path provided
    WHEN constructed
    THEN .a2sdlc/ticket.md exists with that content and get_ticket returns it."""
    src = tmp_path / "source-ticket.md"
    src.write_text("# Ticket body\n\ndo the thing")

    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.SPEC,
        ticket_path=src,
    )

    assert adapter.get_ticket("sid-1") == "# Ticket body\n\ndo the thing"
    assert (
        tmp_path / ".a2sdlc" / "ticket.md"
    ).read_text() == "# Ticket body\n\ndo the thing"


def test_get_ticket_returns_empty_string_when_missing(tmp_path):
    """GIVEN no ticket.md
    WHEN get_ticket is called
    THEN it returns ""."""
    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.SPEC,
        ticket_path=None,
    )

    assert adapter.get_ticket("sid-1") == ""


def test_format_branch_returns_a2sdlc_prefixed_branch(tmp_path):
    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.SPEC,
        ticket_path=None,
    )
    assert adapter.format_branch("abc") == "a2sdlc/abc"


def test_finalize_comment_writes_handover_file_for_active_stage(tmp_path):
    """GIVEN begin_comment then finalize_comment
    WHEN called with active stage SPEC
    THEN .a2sdlc/handover/spec.md contains the body."""
    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.SPEC,
        ticket_path=None,
    )

    cid = adapter.begin_comment("sid-1")
    adapter.finalize_comment(cid, "the spec output")

    handover = tmp_path / ".a2sdlc" / "handover" / "spec.md"
    assert handover.exists()
    assert handover.read_text() == "the spec output"


def test_find_last_handover_returns_newest(tmp_path):
    """GIVEN two handover files written in sequence
    WHEN find_last_handover is called
    THEN it returns the newer file with stage parsed from filename."""
    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.SPEC,
        ticket_path=None,
    )

    handover_dir = tmp_path / ".a2sdlc" / "handover"
    (handover_dir / "spec.md").write_text("spec body")
    time.sleep(0.01)
    (handover_dir / "implement.md").write_text("implement body")

    result = adapter.find_last_handover("sid-1")

    assert result is not None
    assert result.stage == StageName.IMPLEMENT
    assert result.body == "implement body"
    assert result.created_at.tzinfo is not None


def test_find_last_handover_returns_none_when_dir_empty(tmp_path):
    """GIVEN no handover files
    WHEN find_last_handover is called
    THEN it returns None."""
    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.SPEC,
        ticket_path=None,
    )

    assert adapter.find_last_handover("sid-1") is None


def test_constructor_with_ticket_path_none_does_not_overwrite_existing(tmp_path):
    """GIVEN existing .a2sdlc/ticket.md
    WHEN constructed with ticket_path=None
    THEN existing ticket.md is preserved."""
    _mk_a2sdlc(tmp_path)
    (tmp_path / ".a2sdlc" / "ticket.md").write_text("preserved")

    LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.SPEC,
        ticket_path=None,
    )

    assert (tmp_path / ".a2sdlc" / "ticket.md").read_text() == "preserved"


def test_collect_issue_feedback_returns_empty_list(tmp_path):
    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.SPEC,
        ticket_path=None,
    )
    assert adapter.collect_issue_feedback("sid-1", datetime.now(timezone.utc)) == []


def test_get_labels_returns_empty_list(tmp_path):
    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.SPEC,
        ticket_path=None,
    )
    assert adapter.get_labels("sid-1") == []
