import pytest
from a2sdlc_dispatcher.runs_table import RunsTable, RunNotFound


def test_register_and_lookup():
    t = RunsTable()
    t.register(run_id="r1", ticket_key="A2X-1", repo="acme/webapp", project_key="A2X")
    entry = t.get("r1")
    assert entry.ticket_key == "A2X-1"
    assert entry.repo == "acme/webapp"


def test_lookup_unknown_raises():
    t = RunsTable()
    with pytest.raises(RunNotFound):
        t.get("missing")


def test_finish_removes_entry():
    t = RunsTable()
    t.register(run_id="r1", ticket_key="A2X-1", repo="acme/webapp", project_key="A2X")
    t.finish("r1")
    with pytest.raises(RunNotFound):
        t.get("r1")


def test_active_run_for_ticket():
    t = RunsTable()
    t.register(run_id="r1", ticket_key="A2X-1", repo="acme/webapp", project_key="A2X")
    assert t.active_run_for("A2X-1") == "r1"
    t.finish("r1")
    assert t.active_run_for("A2X-1") is None


def test_in_progress_flag_defaults_false_and_flips_once():
    t = RunsTable()
    t.register(run_id="r1", ticket_key="A2X-1", repo="acme/webapp", project_key="A2X")
    assert t.has_in_progress_been_sent("r1") is False
    t.mark_in_progress_sent("r1")
    assert t.has_in_progress_been_sent("r1") is True
    # Idempotent second call is a no-op.
    t.mark_in_progress_sent("r1")
    assert t.has_in_progress_been_sent("r1") is True
