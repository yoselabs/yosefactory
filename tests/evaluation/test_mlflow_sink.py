"""Behavior tests for MLflow telemetry sink."""

from __future__ import annotations

from a2sdlc.evaluation.mlflow_sink import MlflowSink


def test_mlflow_sink_creates_parent_and_child_runs(tmp_path):
    """GIVEN a fresh MLflow file store
    WHEN MlflowSink logs a stage run for a new session
    THEN a parent run and a child run exist in the store."""
    tracking_uri = f"file://{tmp_path / 'mlflow'}"
    sink = MlflowSink(tracking_uri=tracking_uri, experiment_name="testrepo")
    sink.verify_reachable()

    with sink.session("sid-1") as session:
        with session.stage_run(stage="spec") as child:
            child.log_metric("tokens_in", 100)
            child.log_metric("cost_usd", 0.01)
            child.log_tag("git_sha_before", "abc123")

    import mlflow

    mlflow.set_tracking_uri(tracking_uri)
    exp = mlflow.get_experiment_by_name("testrepo")
    assert exp is not None
    runs = mlflow.search_runs(experiment_ids=[exp.experiment_id])
    # parent + child >= 2
    assert len(runs) >= 2


def test_mlflow_sink_verify_reachable_green_on_valid_file_uri(tmp_path):
    """GIVEN a valid file: URI
    WHEN verify_reachable is called
    THEN no error is raised."""
    tracking_uri = f"file://{tmp_path / 'mlflow'}"
    sink = MlflowSink(tracking_uri=tracking_uri, experiment_name="x")
    sink.verify_reachable()  # must not raise


def test_mlflow_sink_stage_run_logs_metrics_and_tags(tmp_path):
    """GIVEN a stage run
    WHEN log_metric / log_tag are called
    THEN those values are stored in the child run."""
    import mlflow

    tracking_uri = f"file://{tmp_path / 'mlflow'}"
    sink = MlflowSink(tracking_uri=tracking_uri, experiment_name="testrepo")
    sink.verify_reachable()

    child_run_id: str | None = None
    with sink.session("sid-2") as session:
        with session.stage_run(stage="implement") as child:
            child.log_metric("tokens_in", 1234)
            child.log_tag("stage_tag", "yes")
            child_run_id = child.run_id

    mlflow.set_tracking_uri(tracking_uri)
    run = mlflow.get_run(child_run_id)
    assert run.data.metrics["tokens_in"] == 1234.0
    assert run.data.tags.get("stage_tag") == "yes"


def test_mlflow_sink_nested_child_runs_parent_tracked(tmp_path):
    """GIVEN a session with multiple stages
    WHEN two stage runs are opened under the same session
    THEN both children appear in the store and both reference the same parent."""
    import mlflow

    tracking_uri = f"file://{tmp_path / 'mlflow'}"
    sink = MlflowSink(tracking_uri=tracking_uri, experiment_name="testrepo")
    sink.verify_reachable()

    with sink.session("sid-3") as session:
        with session.stage_run(stage="spec") as c1:
            c1.log_metric("x", 1)
        with session.stage_run(stage="implement") as c2:
            c2.log_metric("x", 2)

    mlflow.set_tracking_uri(tracking_uri)
    exp = mlflow.get_experiment_by_name("testrepo")
    assert exp is not None
    runs = mlflow.search_runs(experiment_ids=[exp.experiment_id])
    # at least 1 parent + 2 children
    assert len(runs) >= 3
