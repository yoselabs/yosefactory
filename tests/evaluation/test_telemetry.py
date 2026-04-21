"""Tests for the Telemetry abstraction."""

from __future__ import annotations

from a2sdlc.evaluation.telemetry import NoopTelemetry


def test_noop_session_stage_is_safe_noop() -> None:
    t = NoopTelemetry()
    assert t.traces_enabled is False
    with t.session("sid-1") as opener, opener.stage("spec") as run:
        run.log_metric("cost_usd", 1.23)
        run.log_tag("git_sha_before", "abc")
        run.log_dict({"stage": "spec"}, "out.json")
        run.log_artifact("/tmp/quality.log")  # noqa: S108 — path is not read
    # No exception, no state written anywhere.
