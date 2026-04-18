"""Smoke test that ProgressAdapter protocol is defined and structurally correct."""

from a2sdlc.adapters.protocols import ProgressAdapter


def test_progress_adapter_has_expected_methods():
    """GIVEN the ProgressAdapter protocol
    WHEN inspected
    THEN it declares on_stage_start, on_event, on_stage_end, on_group_open, on_group_close."""
    required = {
        "on_stage_start",
        "on_event",
        "on_stage_end",
        "on_group_open",
        "on_group_close",
    }
    declared = {name for name in dir(ProgressAdapter) if not name.startswith("_")}
    assert required.issubset(declared)
