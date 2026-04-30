"""Behavior tests for local_file_work adapter."""

import json
import logging
import shutil
import time
from datetime import datetime, timezone

from a2sdlc.adapters.work.local_file import LocalFileWorkAdapter
from a2sdlc.domain.models import StageName


def _mk_a2sdlc(root):
    (root / ".a2sdlc" / "state").mkdir(parents=True, exist_ok=True)


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
    (tmp_path / ".a2sdlc" / "state" / "pr.json").write_text(
        json.dumps({"pr_number": 1})
    )

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
    (tmp_path / ".a2sdlc" / "state" / "feedback.json").write_text(
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
    (tmp_path / ".a2sdlc" / "state" / "feedback.json").write_text(
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
    THEN .a2sdlc/state/ticket.md exists with that content and get_ticket returns it."""
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
        tmp_path / ".a2sdlc" / "state" / "ticket.md"
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
    THEN .a2sdlc/state/handover/spec.md contains the body."""
    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.SPEC,
        ticket_path=None,
    )

    cid = adapter.begin_comment("sid-1")
    adapter.finalize_comment(cid, "the spec output")

    handover = tmp_path / ".a2sdlc" / "state" / "handover" / "spec.md"
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

    handover_dir = tmp_path / ".a2sdlc" / "state" / "handover"
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
    """GIVEN existing .a2sdlc/state/ticket.md
    WHEN constructed with ticket_path=None
    THEN existing ticket.md is preserved."""
    _mk_a2sdlc(tmp_path)
    (tmp_path / ".a2sdlc" / "state" / "ticket.md").write_text("preserved")

    LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.SPEC,
        ticket_path=None,
    )

    assert (tmp_path / ".a2sdlc" / "state" / "ticket.md").read_text() == "preserved"


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


def test_parse_event_corrupt_pr_json_returns_none_pr_number(tmp_path):
    """GIVEN a non-JSON pr.json on disk
    WHEN parse_event is called
    THEN pr_number is None (JSONDecodeError fallback)."""
    _mk_a2sdlc(tmp_path)
    (tmp_path / ".a2sdlc" / "state" / "pr.json").write_text("{not valid json")

    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.IMPLEMENT,
        ticket_path=None,
    )

    event = adapter.parse_event()

    assert event.pr_number is None


def test_parse_event_pr_json_with_non_int_pr_number_returns_none(tmp_path):
    """GIVEN pr.json where pr_number is a string (not int)
    WHEN parse_event is called
    THEN pr_number is None."""
    _mk_a2sdlc(tmp_path)
    (tmp_path / ".a2sdlc" / "state" / "pr.json").write_text(
        json.dumps({"pr_number": "not-an-int"})
    )

    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.IMPLEMENT,
        ticket_path=None,
    )

    event = adapter.parse_event()

    assert event.pr_number is None


def test_parse_event_corrupt_feedback_json_treated_as_no_feedback(tmp_path):
    """GIVEN a non-JSON feedback.json on disk
    WHEN parse_event is called
    THEN is_feedback is False (JSONDecodeError fallback)."""
    _mk_a2sdlc(tmp_path)
    (tmp_path / ".a2sdlc" / "state" / "feedback.json").write_text("not json at all")

    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.REVIEW,
        ticket_path=None,
    )

    event = adapter.parse_event()

    assert event.is_feedback is False
    assert event.trigger_stage == StageName.REVIEW


def test_parse_event_feedback_without_consumed_key_treated_as_unconsumed(tmp_path):
    """GIVEN feedback.json missing the 'consumed' key
    WHEN parse_event is called
    THEN is_feedback is True (default consumed=False means unconsumed)."""
    _mk_a2sdlc(tmp_path)
    (tmp_path / ".a2sdlc" / "state" / "feedback.json").write_text(
        json.dumps({"body": "x"})
    )

    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.IMPLEMENT,
        ticket_path=None,
    )

    event = adapter.parse_event()

    assert event.is_feedback is True


def test_update_progress_is_a_noop(tmp_path):
    """GIVEN a comment id from begin_comment
    WHEN update_progress is called
    THEN it returns None and does not crash."""
    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.SPEC,
        ticket_path=None,
    )
    cid = adapter.begin_comment("sid-1")
    assert adapter.update_progress(cid, "progress body") is None


def test_set_current_stage_logs_and_does_not_crash(tmp_path, caplog):
    """GIVEN any adapter
    WHEN set_current_stage is called
    THEN an INFO log is emitted naming the stage and key."""
    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.SPEC,
        ticket_path=None,
    )
    with caplog.at_level(logging.INFO, logger="a2sdlc.adapters.work.local_file"):
        adapter.set_current_stage("sid-1", StageName.IMPLEMENT)

    assert any("set_current_stage" in r.message for r in caplog.records)


def test_mark_done_logs_and_does_not_crash(tmp_path, caplog):
    """GIVEN any adapter
    WHEN mark_done is called
    THEN an INFO log is emitted naming the key."""
    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.MERGE,
        ticket_path=None,
    )
    with caplog.at_level(logging.INFO, logger="a2sdlc.adapters.work.local_file"):
        adapter.mark_done("sid-1")

    assert any("mark_done" in r.message for r in caplog.records)


def test_mark_blocked_logs_and_does_not_crash(tmp_path, caplog):
    """GIVEN any adapter
    WHEN mark_blocked is called with a reason
    THEN an INFO log is emitted naming the reason."""
    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.SPEC,
        ticket_path=None,
    )
    with caplog.at_level(logging.INFO, logger="a2sdlc.adapters.work.local_file"):
        adapter.mark_blocked("sid-1", "no upstream")

    assert any("no upstream" in r.message for r in caplog.records)


def test_find_last_handover_returns_none_when_dir_missing(tmp_path):
    """GIVEN handover dir was deleted after construction
    WHEN find_last_handover is called
    THEN it returns None (existence-check guard)."""
    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.SPEC,
        ticket_path=None,
    )

    shutil.rmtree(tmp_path / ".a2sdlc" / "state" / "handover")

    assert adapter.find_last_handover("sid-1") is None


def test_find_last_handover_returns_none_for_unknown_stage_name(tmp_path):
    """GIVEN a handover file with a stem that is not a valid StageName
    WHEN find_last_handover is called
    THEN it returns None (ValueError fallback)."""
    adapter = LocalFileWorkAdapter(
        project_root=tmp_path,
        session_id="sid-1",
        stage=StageName.SPEC,
        ticket_path=None,
    )

    handover_dir = tmp_path / ".a2sdlc" / "state" / "handover"
    (handover_dir / "unknown.md").write_text("garbage stage")

    assert adapter.find_last_handover("sid-1") is None


def test_write_stage_artifact_spec_writes_spec_md(tmp_path) -> None:
    from a2sdlc.adapters.work.local_file import LocalFileWorkAdapter
    from a2sdlc.domain.models import StageName

    adapter = LocalFileWorkAdapter(state_root=tmp_path / ".a2sdlc/state/branchA")
    p = adapter.write_stage_artifact(StageName.SPEC, cycle=1, content="hello\n")
    assert p == tmp_path / ".a2sdlc/state/branchA/spec.md"
    assert p.read_text() == "hello\n"


def test_write_stage_artifact_implement_uses_cycle(tmp_path) -> None:
    from a2sdlc.adapters.work.local_file import LocalFileWorkAdapter
    from a2sdlc.domain.models import StageName

    adapter = LocalFileWorkAdapter(state_root=tmp_path / ".a2sdlc/state/branchA")
    p1 = adapter.write_stage_artifact(StageName.IMPLEMENT, cycle=1, content="c1")
    p2 = adapter.write_stage_artifact(StageName.IMPLEMENT, cycle=2, content="c2")
    assert p1.name == "implement-cycle-1.md"
    assert p2.name == "implement-cycle-2.md"
    assert p1.read_text() == "c1"
    assert p2.read_text() == "c2"


def test_write_stage_artifact_overwrites_for_spec(tmp_path) -> None:
    from a2sdlc.adapters.work.local_file import LocalFileWorkAdapter
    from a2sdlc.domain.models import StageName

    adapter = LocalFileWorkAdapter(state_root=tmp_path / ".a2sdlc/state/branchA")
    adapter.write_stage_artifact(StageName.SPEC, cycle=1, content="first")
    adapter.write_stage_artifact(StageName.SPEC, cycle=1, content="second")
    p = tmp_path / ".a2sdlc/state/branchA/spec.md"
    assert p.read_text() == "second"


def test_write_stage_artifact_raises_for_review_stage(tmp_path) -> None:
    """REVIEW artifacts are owned by the ReviewAdapter, not the WorkAdapter."""
    import pytest

    from a2sdlc.adapters.work.local_file import LocalFileWorkAdapter
    from a2sdlc.domain.models import StageName

    adapter = LocalFileWorkAdapter(state_root=tmp_path / ".a2sdlc/state/branchA")
    with pytest.raises(ValueError, match="REVIEW artifacts are owned"):
        adapter.write_stage_artifact(StageName.REVIEW, cycle=1, content="x")


def test_state_root_property_returns_construction_arg(tmp_path) -> None:
    from a2sdlc.adapters.work.local_file import LocalFileWorkAdapter

    target = tmp_path / ".a2sdlc/state/branchA"
    adapter = LocalFileWorkAdapter(state_root=target)
    assert adapter.state_root == target
