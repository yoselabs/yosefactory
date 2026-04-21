"""Integration test: pipeline.dispatch emits MLflow session + stage runs.

Verifies the telemetry wiring added in Task 6: when a real ``MlflowTelemetry``
is attached to ``DispatchContext``, a completed dispatch produces a parent
``session:<sid>`` run and a nested child ``<sid>:<stage>`` run with the
expected tags and metrics.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from a2sdlc.domain.models import StageName
from a2sdlc.domain.pipeline_event import PipelineEvent
from tests.fakes import make_dispatch_context


@pytest.mark.integration
def test_dispatch_emits_mlflow_runs(tmp_path: Path) -> None:
    """pipeline.dispatch under MlflowTelemetry produces nested session+stage runs."""
    import mlflow

    from a2sdlc.evaluation.telemetry import MlflowTelemetry
    from a2sdlc.pipeline.dispatch import dispatch

    tracking_uri = f"file://{tmp_path / 'mlflow'}"
    telemetry = MlflowTelemetry(
        tracking_uri=tracking_uri, experiment_name="itest-smoke"
    )
    telemetry.verify_reachable()

    # Minimal SPEC event — default_run_result() returns a "complete" status block
    # so dispatch exits the success path and logs metrics.
    ctx, _work, _git, _review, _runner = make_dispatch_context(
        event=PipelineEvent(key="TEST-1", trigger_stage=StageName.SPEC),
        run_id="itest-run-1",
    )
    ctx.telemetry = telemetry

    result = asyncio.run(dispatch(ctx))
    assert not result.blocked, f"dispatch blocked unexpectedly: {result.error}"

    # Read runs back from the file store.
    mlflow.set_tracking_uri(tracking_uri)
    runs = mlflow.search_runs(experiment_names=["itest-smoke"], output_format="list")
    names = {r.data.tags.get("mlflow.runName") for r in runs}

    session_names = [n for n in names if n and n.startswith("session:")]
    child_names = [n for n in names if n and ":" in n and not n.startswith("session:")]

    assert len(session_names) == 1, f"expected one session run, got {session_names}"
    assert len(child_names) >= 1, (
        f"expected at least one stage child run, got {child_names}"
    )

    # Verify required tags on the child run.
    child_run = next(
        r for r in runs if r.data.tags.get("mlflow.runName") in child_names
    )
    assert child_run.data.tags.get("stage") is not None
    assert child_run.data.tags.get("session_id") is not None
    assert child_run.data.tags.get("ticket_key") is not None
    assert child_run.data.tags.get("target_stage") is not None

    # Verify metrics are logged on the success path.
    assert "tokens_in" in child_run.data.metrics
    assert "tokens_out" in child_run.data.metrics
    assert "cost_usd" in child_run.data.metrics
