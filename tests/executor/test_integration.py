"""The integration receipt `add-run-guardrails` recorded as owed.

The wall clock, the turn ceiling and the isolation policy shipped with no caller. Passing unit tests
are not the same claim as a guard that has been observed to fire, so these drive the real binary.

Skipped when `claude` is absent or the pinned version has moved — a receipt against a different
binary is not this receipt, and a capability claim without a check against a pinned version is
invalid by construction.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from yosefactory.executor.claude import PINNED_VERSION, build_argv, resolve_version, run
from yosefactory.executor.outcome import RunOutcome
from yosefactory.executor.stream import StreamReader
from yosefactory.protocol.turn import EnforcedBy, Outcome
from yosefactory.runtime.config import Guardrails
from yosefactory.runtime.isolation import IsolationPolicy
from yosefactory.runtime.runs import read_window
from yosefactory.runtime.supervise import StreamRecorder

pytestmark = pytest.mark.skipif(
    shutil.which("claude") is None or (shutil.which("claude") is not None and resolve_version() != PINNED_VERSION),
    reason=f"needs claude {PINNED_VERSION} on PATH",
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)  # noqa: S607
    (tmp_path / ".gitignore").write_text("runs/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True)  # noqa: S607
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"], cwd=tmp_path, check=True)  # noqa: S607
    return tmp_path


def test_a_real_run_produces_a_structured_outcome(workspace: Path) -> None:
    """Receipt 1: one bounded, isolated invocation, verdict taken from the agent's own terminal event.

    Isolated on a developer host, which is the part that changed. The previous version of this receipt
    opted out and recorded the opt-out as the finding, because the flags it used isolated nothing.
    """
    runs = workspace / "runs"
    result = run(
        {"goal": "Reply with exactly: OK", "method": "answer directly", "assumptions": "none"},
        workspace,
        Guardrails(window=10, wall_clock_seconds=300, turn_ceiling=5, grace_seconds=10, question_deadline_hours=24),
        run_id="receipt1",
        runs_dir=runs,
        recorder=StreamRecorder(runs),
        policy=IsolationPolicy(isolated=True),
    )

    assert result.outcome is RunOutcome.SUCCESS
    assert result.protocol_outcome is Outcome.ADVANCED
    assert result.transcript_path.exists()
    assert result.usage.num_turns >= 1
    # The canary is not free: a cold cache is charged whatever the prompt costs.
    assert result.usage.total_cost_usd > 0

    # `dirty` excludes the harness's own footprint by construction, not by filter: the transcript
    # and the run markers are written inside the stream the supervisor already excludes.
    assert result.dirty is False

    positions = read_window(runs, 10)
    assert [position.outcome for position in positions] == [Outcome.ADVANCED]
    assert positions[0].record is not None
    assert positions[0].record.enforced_by is EnforcedBy.AGENT


def test_an_isolated_run_loads_no_host_or_repository_configuration(workspace: Path) -> None:
    """Receipt 3: the posture asserted from the agent's own init event, on a fully configured host.

    The repository below is hostile on purpose — its own `CLAUDE.md`, skill, agent and tool-server
    config all load under `-p` with no trust dialog. Neither it nor the host's configuration reaches
    an isolated run, and the run says so itself rather than being credited on the strength of the
    arguments it was passed.
    """
    (workspace / "CLAUDE.md").write_text("REPO_CANARY: this must not reach an isolated run.\n", encoding="utf-8")
    skill = workspace / ".claude" / "skills" / "repo-canary"
    skill.mkdir(parents=True)
    skill.joinpath("SKILL.md").write_text("---\nname: repo-canary\ndescription: must not load\n---\nNothing.\n", encoding="utf-8")
    workspace.joinpath(".mcp.json").write_text('{"mcpServers": {"repo-canary": {"command": "/bin/echo"}}}', encoding="utf-8")

    runs = workspace / "runs"
    result = run(
        {"goal": "Reply with exactly: OK"},
        workspace,
        Guardrails(window=10, wall_clock_seconds=300, turn_ceiling=5, grace_seconds=10, question_deadline_hours=24),
        run_id="receipt3",
        runs_dir=runs,
        policy=IsolationPolicy(isolated=True),
    )

    assert result.outcome is RunOutcome.SUCCESS, result.detail
    reader = StreamReader(result.transcript_path)
    reader.poll()
    assert reader.init is not None
    assert reader.init.leaks == ()

    # The floor is not zero, and the residue is recorded rather than asserted away: one host plugin
    # registers under safe mode and no flag unregisters it. It contributes no skills and no commands.
    assert reader.init.skills == ()
    assert reader.init.slash_commands == ()


def test_a_workspace_scoped_run_admits_repo_config_and_excludes_host_config(workspace: Path) -> None:
    """Receipt for `scope-isolation-by-config-source`: the third posture, verified both directions.

    The repository below carries its own `CLAUDE.md`; the host this test runs on carries its own too.
    A workspace-scoped run must report the repository's without reporting a host plugin registration
    — `plugins == ()` is the one surface this posture can assert absent from the init event alone; the
    memory question needs a canary turn, not init, per `run-guardrails/agent-isolation`.
    """
    (workspace / "CLAUDE.md").write_text("REPO_CANARY: workspace-scoped must admit this.\n", encoding="utf-8")

    runs = workspace / "runs"
    result = run(
        {"goal": "Reply with exactly: OK"},
        workspace,
        Guardrails(window=10, wall_clock_seconds=300, turn_ceiling=5, grace_seconds=10, question_deadline_hours=24),
        run_id="receipt-workspace-scoped",
        runs_dir=runs,
        policy=IsolationPolicy(isolated=False, workspace_scoped=True, opt_out_reason="the workspace-scoped receipt"),
    )

    assert result.outcome is RunOutcome.SUCCESS, result.detail
    reader = StreamReader(result.transcript_path)
    reader.poll()
    assert reader.init is not None
    assert reader.init.workspace_scope_leaks == ()


def test_an_opted_out_run_shows_what_isolation_was_holding_back(workspace: Path) -> None:
    """The control for the receipt above, and the reason the assertion is worth anything.

    An identical run with the posture off loads host configuration. Without this, an isolated run
    reporting nothing loaded is equally consistent with a host that had nothing to load.
    """
    runs = workspace / "runs"
    result = run(
        {"goal": "Reply with exactly: OK"},
        workspace,
        Guardrails(window=10, wall_clock_seconds=300, turn_ceiling=5, grace_seconds=10, question_deadline_hours=24),
        run_id="control",
        runs_dir=runs,
        policy=IsolationPolicy(isolated=False, opt_out_reason="the control for the isolation receipt"),
    )

    assert result.outcome is RunOutcome.SUCCESS, result.detail
    reader = StreamReader(result.transcript_path)
    reader.poll()
    assert reader.init is not None
    assert reader.init.leaks, "the host loads nothing, so the isolated receipt proves nothing"


def test_a_run_that_exceeds_its_wall_clock_is_stopped_and_recorded(workspace: Path) -> None:
    """Receipt 2: the harness stop fires, says so, and reports the tree honestly."""
    runs = workspace / "runs"
    (workspace / "half-edited.txt").write_text("the agent was interrupted here\n", encoding="utf-8")

    result = run(
        {"goal": "Count slowly from 1 to 500, one number per line, with a short remark on each."},
        workspace,
        Guardrails(window=10, wall_clock_seconds=5, turn_ceiling=40, grace_seconds=1, question_deadline_hours=24),
        run_id="receipt2",
        runs_dir=runs,
        recorder=StreamRecorder(runs),
    )

    assert result.outcome is not RunOutcome.SUCCESS
    assert result.protocol_outcome is Outcome.FAILED

    positions = read_window(runs, 10)
    assert positions[0].record is not None
    record = positions[0].record
    assert record.outcome is Outcome.FAILED
    assert "wall clock exceeded" in record.note
    # A tree the agent left half-edited reads as dirty; the harness's own transcript never does.
    assert record.dirty is True

    # The agent does flush a terminal verdict inside the grace window, so this passes only because
    # who stopped the run now outranks what the agent managed to say on the way down.
    assert record.enforced_by is EnforcedBy.HARNESS


def test_isolated_invocation_never_reaches_for_bare_mode() -> None:
    """Bare mode buys isolation by making a subscription run unable to authenticate at all."""
    argv = build_argv("hello", IsolationPolicy())
    assert "--bare" not in argv
    assert "--safe-mode" in argv
    assert "--disable-slash-commands" in argv
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--permission-mode") + 1] == "manual"
