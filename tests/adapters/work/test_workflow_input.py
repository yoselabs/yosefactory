from datetime import datetime

import pytest

from a2sdlc.adapters.work.workflow_input import WorkflowInputReader
from a2sdlc.domain.exceptions import SkipEvent
from a2sdlc.domain.models import StageName


def test_parse_event_returns_pipeline_event(monkeypatch):
    monkeypatch.setenv("TICKET_KEY", "A2X-42")
    monkeypatch.setenv("A2SDLC_TRIGGER_STAGE", "spec")
    monkeypatch.setenv("TICKET_BODY", "As a user, I want auth.")
    reader = WorkflowInputReader()
    evt = reader.parse_event()
    assert evt.key == "A2X-42"
    assert evt.trigger_stage == StageName.SPEC


def test_get_ticket_body_returns_env(monkeypatch):
    monkeypatch.setenv("TICKET_KEY", "A2X-42")
    monkeypatch.setenv("TICKET_BODY", "hello world")
    monkeypatch.setenv("A2SDLC_TRIGGER_STAGE", "spec")
    reader = WorkflowInputReader()
    assert reader.get_ticket("A2X-42") == "hello world"


def test_parse_event_skips_when_ticket_key_missing(monkeypatch):
    monkeypatch.delenv("TICKET_KEY", raising=False)
    monkeypatch.setenv("A2SDLC_TRIGGER_STAGE", "spec")
    reader = WorkflowInputReader()
    with pytest.raises(SkipEvent, match="TICKET_KEY not set"):
        reader.parse_event()


def test_parse_event_skips_on_unknown_stage(monkeypatch):
    monkeypatch.setenv("TICKET_KEY", "A2X-42")
    monkeypatch.setenv("A2SDLC_TRIGGER_STAGE", "bogus")
    reader = WorkflowInputReader()
    with pytest.raises(SkipEvent, match="unknown trigger stage"):
        reader.parse_event()


def test_get_ticket_raises_when_body_unset(monkeypatch):
    monkeypatch.delenv("TICKET_BODY", raising=False)
    reader = WorkflowInputReader()
    with pytest.raises(RuntimeError, match="TICKET_BODY"):
        reader.get_ticket("A2X-42")


def test_no_op_write_methods_return_sentinels_or_none():
    reader = WorkflowInputReader()
    # begin_comment returns a sentinel string, not None.
    assert reader.begin_comment("A2X-42") == "dispatcher-routed"
    # All other writes are no-ops.
    assert reader.update_progress("id", "body") is None
    assert reader.finalize_comment("id", "body") is None
    assert reader.set_current_stage("A2X-42", StageName.IMPLEMENT) is None
    assert reader.mark_done("A2X-42") is None
    assert reader.mark_blocked("A2X-42", "reason") is None
    # Read-only no-ops.
    assert reader.get_labels("A2X-42") == []
    assert reader.find_last_handover("A2X-42") is None
    assert reader.collect_issue_feedback("A2X-42", datetime.now()) == []
    # format_branch follows the engine's convention.
    assert reader.format_branch("A2X-42") == "agent/A2X-42"
