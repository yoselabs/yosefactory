"""Quality gate behavior tests."""

from a2sdlc.evaluation.quality_gate import run_quality_gate


def test_quality_gate_passes_when_command_exits_zero(tmp_path):
    """GIVEN a command that exits 0
    WHEN the gate runs
    THEN result.passed is True and exit_code is 0."""
    result = run_quality_gate(project_root=tmp_path, command="true")
    assert result.passed is True
    assert result.exit_code == 0


def test_quality_gate_fails_when_command_exits_nonzero(tmp_path):
    """GIVEN a command that exits nonzero
    WHEN the gate runs
    THEN result.passed is False."""
    result = run_quality_gate(project_root=tmp_path, command="false")
    assert result.passed is False
    assert result.exit_code != 0


def test_quality_gate_captures_stdout(tmp_path):
    """GIVEN a command that writes to stdout
    WHEN the gate runs
    THEN result.output contains that text."""
    result = run_quality_gate(project_root=tmp_path, command="echo hello")
    assert "hello" in result.output


def test_quality_gate_captures_stderr(tmp_path):
    """GIVEN a command that writes to stderr
    WHEN the gate runs
    THEN result.output contains that text too."""
    result = run_quality_gate(project_root=tmp_path, command="echo oops >&2")
    assert "oops" in result.output


def test_quality_gate_runs_in_project_root(tmp_path):
    """GIVEN a command that prints cwd
    WHEN the gate runs with project_root=tmp_path
    THEN the printed cwd is the tmp_path."""
    result = run_quality_gate(project_root=tmp_path, command="pwd")
    assert str(tmp_path) in result.output
