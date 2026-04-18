"""Behavior test for GH Actions progress adapter."""

from a2sdlc.adapters.progress_gh_actions import GhActionsProgressAdapter
from a2sdlc.domain.models import StageName


def test_gh_actions_adapter_emits_group_markers(capsys):
    """GIVEN a GH Actions progress adapter
    WHEN a group is opened and closed
    THEN ::group:: and ::endgroup:: are printed."""
    adapter = GhActionsProgressAdapter()
    adapter.on_group_open("Agent output (123 chars)")
    adapter.on_group_close()

    out = capsys.readouterr().out
    assert "::group::Agent output (123 chars)" in out
    assert "::endgroup::" in out


def test_gh_actions_adapter_forwards_event_text(capsys):
    """GIVEN an event with text
    WHEN on_event is called
    THEN the text is printed."""
    adapter = GhActionsProgressAdapter()
    adapter.on_event("tool_use", "Read(/path/to/file)")
    out = capsys.readouterr().out
    assert "Read(/path/to/file)" in out


def test_gh_actions_adapter_stage_start_emits_group_marker(capsys):
    """GIVEN a stage start event
    WHEN on_stage_start is called
    THEN a ::group:: marker with the stage name is printed."""
    adapter = GhActionsProgressAdapter()
    adapter.on_stage_start(StageName.IMPLEMENT, "sid-123")
    out = capsys.readouterr().out
    assert "::group::" in out
    assert "implement" in out
    assert "sid-123" in out


def test_gh_actions_adapter_stage_end_closes_group_and_reports_status(capsys):
    """GIVEN a stage that ends successfully
    WHEN on_stage_end is called with success=True
    THEN the status is printed and ::endgroup:: follows."""
    adapter = GhActionsProgressAdapter()
    adapter.on_stage_end(StageName.SPEC, True)
    out = capsys.readouterr().out
    assert "OK" in out
    assert "::endgroup::" in out
