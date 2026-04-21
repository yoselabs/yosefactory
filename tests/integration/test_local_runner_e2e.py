"""End-to-end smoke: run-stage spec then run-stage implement against a temp repo.

These tests drive the local runner CLI through two sequential stages using
``FakeStageRunner`` (injected via the ``runner=`` kwarg) to avoid calling out to
the Anthropic SDK. They assert on the observable side effects the engine is
responsible for: session branch creation, ``.a2sdlc/state/pr.json`` from the
``local_noop`` review adapter, ``.a2sdlc/state/state.json`` from the git state manager,
the per-stage handover file written by ``local_file`` work adapter on
``finalize_comment``, and MLflow parent/child runs when tracking is enabled.

FakeStageRunner findings (see tests/fakes.py):
  * Emits a valid ``a2sdlc`` status block so dispatch treats the stage as
    successful.
  * Returns a ``RunResult`` whose ``output`` contains the formatted body, so
    ``finalize_comment`` fires on the work adapter, which (for ``local_file``)
    persists ``.a2sdlc/state/handover/<stage>.md``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from a2sdlc.cli.run_stage import run_stage_entry
from tests.fakes import FakeStageRunner


def _init_minimal_repo(tmp_path: Path, ticket_body: str = "Add hello world") -> Path:
    """Minimal repo fixture: git init, .a2sdlc/config.yaml, a ticket file."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / ".a2sdlc").mkdir()
    (tmp_path / ".a2sdlc" / "config.yaml").write_text(
        "adapters:\n"
        "  work: local_file\n"
        "  review: local_noop\n"
        "  git: local_branch\n"
        "  progress: gh_actions\n"
        "spec:\n  self_answer: true\n"
        "quality:\n  check_command: 'true'\n"
        "model: claude-sonnet-4-6\n"
    )
    ticket = tmp_path / "ticket.md"
    ticket.write_text(ticket_body)
    (tmp_path / "README.md").write_text("init")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    return ticket


def test_e2e_spec_then_implement_against_minimal_repo(tmp_path: Path) -> None:
    """GIVEN a minimal repo with .a2sdlc/config.yaml and a ticket
    WHEN run-stage spec then run-stage implement are invoked
    THEN session branch, handover files, pr.json, state.json all exist
    AND the implement exit code is 0 (quality gate 'true' passes).
    """
    ticket = _init_minimal_repo(tmp_path)

    rc = run_stage_entry(
        argv=[
            "spec",
            "--session",
            "e2e",
            "--ticket",
            str(ticket),
            "--no-track",
            str(tmp_path),
        ],
        runner=FakeStageRunner(),
    )
    assert rc == 0

    # Post-SPEC invariants
    assert (
        tmp_path / ".a2sdlc" / "state" / "ticket.md"
    ).read_text() == "Add hello world"

    pr_data = json.loads((tmp_path / ".a2sdlc" / "state" / "pr.json").read_text())
    assert pr_data["pr_number"] == 1
    assert pr_data["status"] == "draft"

    # state.json exists and is valid JSON
    state_path = tmp_path / ".a2sdlc" / "state" / "state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert state["branch"] == "a2sdlc/e2e"
    assert state["stage"] == "spec"

    # FakeStageRunner's output goes through finalize_comment → handover/<stage>.md
    assert (tmp_path / ".a2sdlc" / "state" / "handover" / "spec.md").exists()

    # Branch check after SPEC
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert branch == "a2sdlc/e2e"

    # Implement
    rc = run_stage_entry(
        argv=["implement", "--session", "e2e", "--no-track", str(tmp_path)],
        runner=FakeStageRunner(),
    )
    assert rc == 0

    # Post-IMPLEMENT invariants
    assert (tmp_path / ".a2sdlc" / "state" / "handover" / "implement.md").exists()
    state_after = json.loads(state_path.read_text())
    assert state_after["stage"] == "implement"

    # Branch check still sits on the session branch
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert branch == "a2sdlc/e2e"


def test_e2e_with_mlflow_tracking_creates_runs(tmp_path: Path, monkeypatch) -> None:
    """GIVEN tracking is enabled (HOME redirected to tmp_path so MLflow writes there)
    WHEN run-stage spec then implement runs
    THEN the MLflow store contains at least one parent session run + 2 stage child runs.
    """
    import mlflow

    # Pin MLFLOW_TRACKING_URI explicitly so local_fallback_telemetry writes to our
    # tmp_path regardless of any MLFLOW_TRACKING_URI left in the env by a previous
    # test (mlflow.set_tracking_uri also sets the env var, which can leak across
    # tests that run sequentially in the same worker).
    mlflow_uri = f"file://{tmp_path / '.a2sdlc' / 'mlflow'}"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", mlflow_uri)

    ticket = _init_minimal_repo(tmp_path, "ticket for tracking")

    rc = run_stage_entry(
        argv=["spec", "--session", "trk", "--ticket", str(ticket), str(tmp_path)],
        runner=FakeStageRunner(),
    )
    assert rc == 0

    rc = run_stage_entry(
        argv=["implement", "--session", "trk", str(tmp_path)],
        runner=FakeStageRunner(),
    )
    assert rc == 0

    # mlflow_uri already set via monkeypatch above; just ensure the global matches.
    mlflow.set_tracking_uri(mlflow_uri)
    exp = mlflow.get_experiment_by_name(tmp_path.name)
    assert exp is not None
    runs = mlflow.search_runs(experiment_ids=[exp.experiment_id], output_format="list")
    # Expect at least: 1 parent session run + 2 stage runs (spec, implement).
    assert len(runs) >= 3


def test_e2e_tracking_writes_output_json_artifact_per_stage(
    tmp_path: Path, monkeypatch
) -> None:
    """GIVEN tracking is enabled and both stages run
    WHEN the run completes
    THEN every stage child run has a ``<stage>-output.json`` artifact whose
         contents carry stage, session_id, success, and the agent output;
         exactly one ``session:trk2`` parent run exists (reuse across calls);
         each child run has a linked MLflow trace from MlflowTraceSubscriber."""
    import mlflow

    # Pin MLFLOW_TRACKING_URI explicitly (same reason as test_e2e_with_mlflow_tracking_creates_runs).
    mlflow_uri = f"file://{tmp_path / '.a2sdlc' / 'mlflow'}"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", mlflow_uri)
    ticket = _init_minimal_repo(tmp_path, "ticket for artifact test")

    rc = run_stage_entry(
        argv=["spec", "--session", "trk2", "--ticket", str(ticket), str(tmp_path)],
        runner=FakeStageRunner(),
    )
    assert rc == 0

    rc = run_stage_entry(
        argv=["implement", "--session", "trk2", str(tmp_path)],
        runner=FakeStageRunner(),
    )
    assert rc == 0

    mlflow.set_tracking_uri(mlflow_uri)
    exp = mlflow.get_experiment_by_name(tmp_path.name)
    assert exp is not None

    parent_runs = mlflow.search_runs(
        experiment_ids=[exp.experiment_id],
        filter_string="tags.mlflow.runName = 'session:trk2'",
        output_format="list",
    )
    assert len(parent_runs) == 1, "parent run must be reused across CLI invocations"
    parent_id = parent_runs[0].info.run_id

    child_by_stage: dict[str, str] = {}
    for stage_name in ("spec", "implement"):
        children = mlflow.search_runs(
            experiment_ids=[exp.experiment_id],
            filter_string=(
                f"tags.mlflow.runName = 'trk2:{stage_name}' "
                f"and tags.mlflow.parentRunId = '{parent_id}'"
            ),
            output_format="list",
        )
        assert len(children) == 1, f"missing {stage_name} child run under parent"
        child_by_stage[stage_name] = children[0].info.run_id

    # ── JSON output artifact per stage ────────────────────────────────
    for stage_name, run_id in child_by_stage.items():
        artifact_dir = tmp_path / ".a2sdlc" / "mlflow" / exp.experiment_id / run_id
        artifact_path = artifact_dir / "artifacts" / f"{stage_name}-output.json"
        assert artifact_path.exists(), f"missing {artifact_path}"
        payload = json.loads(artifact_path.read_text())
        assert payload["stage"] == stage_name
        assert payload["session_id"] == "trk2"
        assert payload["success"] is True
        assert payload["blocked"] is False
        assert payload["error"] is None
        assert isinstance(payload["output"], str) and len(payload["output"]) > 0
        assert isinstance(payload["stats"], dict)

    # ── MLflow trace produced by MlflowTraceSubscriber ────────────────
    traces = mlflow.search_traces(experiment_ids=[exp.experiment_id], max_results=10)
    trace_source_runs = {
        t.trace_metadata.get("mlflow.sourceRun") for _, t in traces.iterrows()
    }
    for run_id in child_by_stage.values():
        assert run_id in trace_source_runs, (
            f"no trace linked to child run {run_id} — MlflowTraceSubscriber "
            f"did not emit spans"
        )
