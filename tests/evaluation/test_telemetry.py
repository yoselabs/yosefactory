"""Tests for the Telemetry abstraction."""

from __future__ import annotations

from pathlib import Path

import mlflow
import pytest

from a2sdlc.evaluation.telemetry import (
    MlflowTelemetry,
    MlflowUnreachableError,
    NoopTelemetry,
    Telemetry,
)


def test_noop_session_stage_is_safe_noop() -> None:
    t = NoopTelemetry()
    assert t.traces_enabled is False
    with t.session("sid-1") as opener, opener.stage("spec") as run:
        run.log_metric("cost_usd", 1.23)
        run.log_tag("git_sha_before", "abc")
        run.log_dict({"stage": "spec"}, "out.json")
        run.log_artifact("/tmp/quality.log")  # noqa: S108 — path is not read
    # No exception, no state written anywhere.


def test_noop_satisfies_telemetry_protocol() -> None:
    # Structural-subtype check — proves the null object conforms at runtime
    # and guards against silent Protocol drift in later tasks.
    assert isinstance(NoopTelemetry(), Telemetry)


def test_noop_traces_enabled_is_false_sentinel() -> None:
    assert NoopTelemetry().traces_enabled is False


# ── MLflow implementation tests ────────────────────────────────────────


def _uri(tmp_path: Path) -> str:
    return f"file://{tmp_path / 'mlflow'}"


def test_mlflow_telemetry_opens_session_and_stage_runs(tmp_path: Path) -> None:
    t = MlflowTelemetry(tracking_uri=_uri(tmp_path), experiment_name="testrepo")
    t.verify_reachable()
    with t.session("sess-1") as opener, opener.stage("spec") as run:
        run.log_metric("cost_usd", 1.23)
        run.log_tag("git_sha_before", "abc123")

    mlflow.set_tracking_uri(_uri(tmp_path))
    runs = mlflow.search_runs(experiment_names=["testrepo"], output_format="list")
    names = {r.data.tags.get("mlflow.runName") for r in runs}
    assert "session:sess-1" in names
    assert "sess-1:spec" in names


def test_mlflow_telemetry_reuses_existing_session(tmp_path: Path) -> None:
    t = MlflowTelemetry(tracking_uri=_uri(tmp_path), experiment_name="testrepo")
    t.verify_reachable()
    with t.session("sess-1") as opener, opener.stage("spec"):
        pass
    with t.session("sess-1") as opener, opener.stage("implement"):
        pass

    mlflow.set_tracking_uri(_uri(tmp_path))
    parent_runs = [
        r
        for r in mlflow.search_runs(experiment_names=["testrepo"], output_format="list")
        if r.data.tags.get("mlflow.runName") == "session:sess-1"
    ]
    assert len(parent_runs) == 1


def test_mlflow_telemetry_verify_reachable_raises_on_bad_uri() -> None:
    # localhost:1 fails immediately with ECONNREFUSED on macOS — no DNS round-trip.
    t = MlflowTelemetry(tracking_uri="http://localhost:1/", experiment_name="x")
    with pytest.raises(MlflowUnreachableError):
        t.verify_reachable()


def test_mlflow_telemetry_traces_enabled_is_true() -> None:
    t = MlflowTelemetry(tracking_uri="http://127.0.0.1:1/bad", experiment_name="x")
    assert t.traces_enabled is True
