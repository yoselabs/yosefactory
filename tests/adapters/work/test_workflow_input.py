from a2sdlc.adapters.work.workflow_input import WorkflowInputReader
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
