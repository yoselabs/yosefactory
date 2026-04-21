"""CLI smoke tests for the ``run-stage`` subcommand."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.fakes import FakeStageRunner


def _init_minimal_repo(tmp_path: Path, ticket_body: str = "Build feature X") -> Path:
    """Initialize a minimal git repo with .a2sdlc/config.yaml and a ticket file.

    Returns the ticket file path.
    """
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


def test_run_stage_spec_creates_session_branch_and_persists_ticket(
    tmp_path: Path,
) -> None:
    """GIVEN a minimal repo and a ticket file
    WHEN run-stage spec --ticket <file> --session testsid is invoked
    THEN a2sdlc/testsid branch exists AND .a2sdlc/state/ticket.md matches the ticket.
    """
    from a2sdlc.cli.run_stage import run_stage_entry

    ticket = _init_minimal_repo(tmp_path)

    exit_code = run_stage_entry(
        argv=[
            "spec",
            "--session",
            "testsid",
            "--ticket",
            str(ticket),
            "--no-track",
            str(tmp_path),
        ],
        runner=FakeStageRunner(),
    )
    assert exit_code == 0

    branch_check = subprocess.run(
        ["git", "rev-parse", "--verify", "a2sdlc/testsid"],
        cwd=tmp_path,
        capture_output=True,
    )
    assert branch_check.returncode == 0

    assert (
        tmp_path / ".a2sdlc" / "state" / "ticket.md"
    ).read_text() == "Build feature X"


def test_run_stage_spec_generates_ulid_when_session_not_given(tmp_path: Path) -> None:
    """GIVEN run-stage spec without --session
    WHEN invoked from a fresh repo
    THEN a ULID-like session id is generated and a branch with that id exists.
    """
    from a2sdlc.cli.run_stage import run_stage_entry

    ticket = _init_minimal_repo(tmp_path)
    exit_code = run_stage_entry(
        argv=["spec", "--ticket", str(ticket), "--no-track", str(tmp_path)],
        runner=FakeStageRunner(),
    )
    assert exit_code == 0

    branches = subprocess.run(
        ["git", "branch", "--list", "a2sdlc/*"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    ).stdout
    assert "a2sdlc/" in branches


def test_run_stage_implement_infers_session_from_branch(tmp_path: Path) -> None:
    """GIVEN we are on branch a2sdlc/fromBranch with existing .a2sdlc/state/ticket.md
    WHEN run-stage implement is invoked without --session
    THEN session_id 'fromBranch' is used (no new branch created).
    """
    from a2sdlc.cli.run_stage import run_stage_entry

    _init_minimal_repo(tmp_path)
    ticket = tmp_path / "ticket.md"
    run_stage_entry(
        argv=[
            "spec",
            "--session",
            "fromBranch",
            "--ticket",
            str(ticket),
            "--no-track",
            str(tmp_path),
        ],
        runner=FakeStageRunner(),
    )

    exit_code = run_stage_entry(
        argv=["implement", "--no-track", str(tmp_path)],
        runner=FakeStageRunner(),
    )
    assert exit_code == 0

    branches = subprocess.run(
        ["git", "branch", "--list", "a2sdlc/*"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    ).stdout
    assert branches.count("a2sdlc/") == 1


def test_run_stage_implement_with_tracking_logs_quality_gate(
    tmp_path: Path, monkeypatch
) -> None:
    """GIVEN tracking is enabled against a local MLflow file store
    WHEN run-stage implement completes
    THEN the quality gate runs inside the stage_run, the metric
         quality_passed=1 is logged, and exit code is 0.
    """
    from a2sdlc.cli.run_stage import run_stage_entry

    _init_minimal_repo(tmp_path)
    ticket = tmp_path / "ticket.md"

    # Pin MLFLOW_TRACKING_URI explicitly so local_fallback_telemetry writes to our
    # tmp_path regardless of any MLFLOW_TRACKING_URI left in the env by a previous
    # test (mlflow.set_tracking_uri also sets the env var, which leaks across tests
    # that run sequentially in the same worker under pytest-xdist).
    mlflow_uri = f"file://{tmp_path / '.a2sdlc' / 'mlflow'}"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", mlflow_uri)

    run_stage_entry(
        argv=[
            "spec",
            "--session",
            "trk",
            "--ticket",
            str(ticket),
            str(tmp_path),
        ],
        runner=FakeStageRunner(),
    )
    rc = run_stage_entry(
        argv=["implement", "--session", "trk", str(tmp_path)],
        runner=FakeStageRunner(),
    )
    assert rc == 0

    import mlflow

    mlflow.set_tracking_uri(mlflow_uri)
    exp = mlflow.get_experiment_by_name(tmp_path.name)
    assert exp is not None
    runs = mlflow.search_runs(experiment_ids=[exp.experiment_id], output_format="list")
    # Look for a child run that logged quality_passed=1.
    assert any(r.data.metrics.get("quality_passed") == 1.0 for r in runs)


def test_run_stage_implement_quality_gate_pass_exits_zero(tmp_path: Path) -> None:
    """GIVEN config.quality.check_command='true' (always passes)
    WHEN run-stage implement runs successfully
    THEN exit code is 0.
    """
    from a2sdlc.cli.run_stage import run_stage_entry

    _init_minimal_repo(tmp_path)
    ticket = tmp_path / "ticket.md"

    run_stage_entry(
        argv=[
            "spec",
            "--session",
            "q",
            "--ticket",
            str(ticket),
            "--no-track",
            str(tmp_path),
        ],
        runner=FakeStageRunner(),
    )
    rc = run_stage_entry(
        argv=["implement", "--session", "q", "--no-track", str(tmp_path)],
        runner=FakeStageRunner(),
    )
    assert rc == 0


def test_run_stage_implement_quality_gate_fail_exits_nonzero(tmp_path: Path) -> None:
    """GIVEN config.quality.check_command='false' (always fails)
    WHEN run-stage implement completes
    THEN exit code is non-zero.
    """
    from a2sdlc.cli.run_stage import run_stage_entry

    _init_minimal_repo(tmp_path)
    cfg = tmp_path / ".a2sdlc" / "config.yaml"
    cfg.write_text(cfg.read_text().replace("'true'", "'false'"))
    ticket = tmp_path / "ticket.md"

    run_stage_entry(
        argv=[
            "spec",
            "--session",
            "f",
            "--ticket",
            str(ticket),
            "--no-track",
            str(tmp_path),
        ],
        runner=FakeStageRunner(),
    )
    rc = run_stage_entry(
        argv=["implement", "--session", "f", "--no-track", str(tmp_path)],
        runner=FakeStageRunner(),
    )
    assert rc != 0


def test_run_stage_spec_requires_ticket_on_first_invocation(
    tmp_path: Path, capsys
) -> None:
    """GIVEN no existing .a2sdlc/state/ticket.md
    WHEN run-stage spec is invoked without --ticket
    THEN exit code is non-zero and a helpful error is shown.
    """
    from a2sdlc.cli.run_stage import run_stage_entry

    _init_minimal_repo(tmp_path)
    (tmp_path / ".a2sdlc" / "state" / "ticket.md").unlink(missing_ok=True)

    exit_code = run_stage_entry(
        argv=["spec", "--session", "x", "--no-track", str(tmp_path)],
        runner=FakeStageRunner(),
    )
    assert exit_code != 0
