"""End-to-end smoke: run-stage spec then run-stage implement against a temp repo.

These tests drive the local runner CLI through two sequential stages using
``FakeStageRunner`` (via ``runner_override='fake'``) to avoid calling out to the
Anthropic SDK. They assert on the observable side effects the engine is
responsible for: session branch creation, ``.a2sdlc/pr.json`` from the
``local_noop`` review adapter, ``.a2sdlc/state.json`` from the git state manager,
the per-stage handover file written by ``local_file`` work adapter on
``finalize_comment``, and MLflow parent/child runs when tracking is enabled.

FakeStageRunner findings (see tests/fakes.py):
  * Emits a valid ``a2sdlc`` status block so dispatch treats the stage as
    successful.
  * Returns a ``RunResult`` whose ``output`` contains the formatted body, so
    ``finalize_comment`` fires on the work adapter, which (for ``local_file``)
    persists ``.a2sdlc/handover/<stage>.md``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from a2sdlc.cli_local import run_stage_entry


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
        runner_override="fake",
    )
    assert rc == 0

    # Post-SPEC invariants
    assert (tmp_path / ".a2sdlc" / "ticket.md").read_text() == "Add hello world"

    pr_data = json.loads((tmp_path / ".a2sdlc" / "pr.json").read_text())
    assert pr_data["pr_number"] == 1
    assert pr_data["status"] == "draft"

    # state.json exists and is valid JSON
    state_path = tmp_path / ".a2sdlc" / "state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert state["branch"] == "a2sdlc/e2e"
    assert state["stage"] == "spec"

    # FakeStageRunner's output goes through finalize_comment → handover/<stage>.md
    assert (tmp_path / ".a2sdlc" / "handover" / "spec.md").exists()

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
        runner_override="fake",
    )
    assert rc == 0

    # Post-IMPLEMENT invariants
    assert (tmp_path / ".a2sdlc" / "handover" / "implement.md").exists()
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

    # Redirect HOME so the MlflowSink's file store lives inside tmp_path.
    monkeypatch.setenv("HOME", str(tmp_path))

    ticket = _init_minimal_repo(tmp_path, "ticket for tracking")

    rc = run_stage_entry(
        argv=["spec", "--session", "trk", "--ticket", str(ticket), str(tmp_path)],
        runner_override="fake",
    )
    assert rc == 0

    rc = run_stage_entry(
        argv=["implement", "--session", "trk", str(tmp_path)],
        runner_override="fake",
    )
    assert rc == 0

    mlflow.set_tracking_uri(f"file://{tmp_path / '.a2sdlc' / 'mlflow'}")
    exp = mlflow.get_experiment_by_name(tmp_path.name)
    assert exp is not None
    runs = mlflow.search_runs(experiment_ids=[exp.experiment_id], output_format="list")
    # Expect at least: 1 parent session run + 2 stage runs (spec, implement).
    assert len(runs) >= 3
