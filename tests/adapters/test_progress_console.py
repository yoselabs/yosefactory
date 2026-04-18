"""Behavior tests for ConsoleProgressAdapter.

rich.Live is hard to capture via capsys; test adapter internal state instead.
Visual inspection happens during manual integration.
"""

from a2sdlc.adapters.progress_console import ConsoleProgressAdapter
from a2sdlc.domain.models import StageName


def test_console_adapter_records_active_stage_on_start():
    """GIVEN a fresh adapter
    WHEN on_stage_start fires
    THEN active_stage and session_id are stored."""
    adapter = ConsoleProgressAdapter()
    adapter.on_stage_start(StageName.SPEC, "01HX123")
    assert adapter.active_stage == StageName.SPEC
    assert adapter.session_id == "01HX123"
    adapter.on_stage_end(StageName.SPEC, True)  # teardown live


def test_console_adapter_accumulates_events():
    """GIVEN a running stage
    WHEN on_event is called multiple times
    THEN events accumulate in the scroll buffer up to max size."""
    adapter = ConsoleProgressAdapter()
    adapter.on_stage_start(StageName.SPEC, "sid")
    adapter.on_event("tool_use", "Read(foo.py)")
    adapter.on_event("text", "Analyzing...")
    assert len(adapter.recent_events) == 2
    assert "Read(foo.py)" in adapter.recent_events[0]
    adapter.on_stage_end(StageName.SPEC, True)


def test_console_adapter_scroll_buffer_capped():
    """GIVEN many events
    WHEN more than MAX_EVENTS fire
    THEN the oldest events are dropped."""
    adapter = ConsoleProgressAdapter()
    adapter.on_stage_start(StageName.SPEC, "sid")
    for i in range(30):
        adapter.on_event("text", f"event {i}")
    assert len(adapter.recent_events) <= 20
    # Most recent is present
    assert "event 29" in adapter.recent_events[-1]
    adapter.on_stage_end(StageName.SPEC, True)


def test_console_adapter_update_metrics_renders_in_status_bar():
    """GIVEN a stage in progress
    WHEN update_metrics sets tokens/cost/turns
    THEN render_status_bar returns a string containing them."""
    adapter = ConsoleProgressAdapter()
    adapter.on_stage_start(StageName.IMPLEMENT, "sid")
    adapter.update_metrics(tokens_in=1000, tokens_out=500, cost_usd=0.03, turns=2)
    status = adapter.render_status_bar()
    assert "1000" in status
    assert "500" in status
    assert "0.03" in status or "$0.03" in status
    assert "2" in status
    adapter.on_stage_end(StageName.IMPLEMENT, True)


def test_console_adapter_group_open_and_close_append_markers():
    """GIVEN a stage
    WHEN on_group_open / on_group_close fire
    THEN marker lines appear in recent_events."""
    adapter = ConsoleProgressAdapter()
    adapter.on_stage_start(StageName.SPEC, "sid")
    adapter.on_group_open("Agent output (123 chars)")
    adapter.on_group_close()
    assert any("Agent output (123 chars)" in line for line in adapter.recent_events)
    assert any(
        "end" in line.lower() or "close" in line.lower()
        for line in adapter.recent_events
    )
    adapter.on_stage_end(StageName.SPEC, True)


def test_console_adapter_stage_end_closes_live_context():
    """GIVEN a running live context
    WHEN on_stage_end fires
    THEN the live context is cleaned up (no residual Live object)."""
    adapter = ConsoleProgressAdapter()
    adapter.on_stage_start(StageName.SPEC, "sid")
    assert adapter._live is not None
    adapter.on_stage_end(StageName.SPEC, True)
    assert adapter._live is None
