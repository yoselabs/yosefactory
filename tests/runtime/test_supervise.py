"""The supervisor, driven by real short-lived subprocesses rather than by a mock of one.

A guard whose only caller does not exist has never been proven to fire. These tests are the closest
available substitute until the executor change wires it up: real processes that overrun, exit
non-zero, produce no verdict, and leave the tree dirty.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from yosefactory.protocol.turn import EnforcedBy, FailureKind, Outcome
from yosefactory.runtime.config import Guardrails
from yosefactory.runtime.runs import read_window
from yosefactory.runtime.supervise import LockBusy, StreamRecorder, SupervisorError, govern, single_flight, tree_is_dirty

SLEEPER = [sys.executable, "-c", "import time; time.sleep(30)"]
QUICK = [sys.executable, "-c", "pass"]
BROKEN = [sys.executable, "-c", "raise SystemExit(3)"]


def guard(**overrides: int) -> Guardrails:
    base = {"window": 5, "wall_clock_seconds": 1, "turn_ceiling": 5, "grace_seconds": 1, "question_deadline_hours": 24}
    return Guardrails(**{**base, **overrides})  # type: ignore[arg-type]


def git(repo: Path, *args: str) -> None:
    binary = shutil.which("git")
    assert binary is not None
    subprocess.run([binary, *args], cwd=repo, capture_output=True, text=True, check=True)  # noqa: S603


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.invalid")
    git(tmp_path, "config", "user.name", "T")
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    git(tmp_path, "add", "a.txt")
    git(tmp_path, "commit", "-q", "-m", "first")
    return tmp_path


def test_a_run_with_no_turn_ceiling_does_not_start(repo: Path) -> None:
    with pytest.raises(SupervisorError, match="no default in any executor"):
        govern(QUICK, repo=repo, runs_dir=repo / "runs", run_id="r1", guard=guard(), turn_ceiling=None)


def test_an_overrunning_run_is_terminated_and_still_leaves_a_record(repo: Path) -> None:
    record = govern(SLEEPER, repo=repo, runs_dir=repo / "runs", run_id="r1", guard=guard(wall_clock_seconds=1), turn_ceiling=5)

    assert record.outcome is Outcome.FAILED
    assert record.enforced_by is EnforcedBy.HARNESS
    assert "wall clock exceeded" in record.note


def test_the_turn_ceiling_terminates_a_run(repo: Path) -> None:
    counter = iter(range(100))

    record = govern(
        SLEEPER,
        repo=repo,
        runs_dir=repo / "runs",
        run_id="r1",
        guard=guard(wall_clock_seconds=30),
        turn_ceiling=3,
        turns_taken=lambda: next(counter),
    )

    assert record.enforced_by is EnforcedBy.HARNESS
    assert "turn ceiling exceeded" in record.note


def test_a_kill_mid_edit_is_recorded_as_dirty(repo: Path) -> None:
    dirtying = [sys.executable, "-c", "import pathlib, time; pathlib.Path('b.txt').write_text('x'); time.sleep(30)"]

    record = govern(dirtying, repo=repo, runs_dir=repo / "runs", run_id="r1", guard=guard(wall_clock_seconds=1), turn_ceiling=5)

    assert record.dirty is True


def test_a_clean_completion_is_not_recorded_as_dirty(repo: Path) -> None:
    record = govern(
        QUICK, repo=repo, runs_dir=repo / "runs", run_id="r1", guard=guard(), turn_ceiling=5, verdict=lambda: Outcome.ADVANCED
    )
    assert record.dirty is False


def test_an_agent_that_flushes_its_own_verdict_owns_the_record(repo: Path) -> None:
    record = govern(
        QUICK, repo=repo, runs_dir=repo / "runs", run_id="r1", guard=guard(), turn_ceiling=5, verdict=lambda: Outcome.ADVANCED
    )

    assert record.enforced_by is EnforcedBy.AGENT
    assert record.outcome is Outcome.ADVANCED


def test_a_run_producing_no_verdict_is_failed_even_on_exit_zero(repo: Path) -> None:
    record = govern(QUICK, repo=repo, runs_dir=repo / "runs", run_id="r1", guard=guard(), turn_ceiling=5, verdict=lambda: None)

    assert record.outcome is Outcome.FAILED
    assert "exit=0" in record.note


def test_a_non_zero_exit_without_a_verdict_is_failed(repo: Path) -> None:
    record = govern(BROKEN, repo=repo, runs_dir=repo / "runs", run_id="r1", guard=guard(), turn_ceiling=5)

    assert record.outcome is Outcome.FAILED
    assert "exit=3" in record.note


def test_the_record_lands_in_the_stream_and_satisfies_its_marker(repo: Path) -> None:
    govern(
        QUICK,
        repo=repo,
        runs_dir=repo / "runs",
        run_id="r1",
        guard=guard(),
        turn_ceiling=5,
        verdict=lambda: Outcome.ADVANCED,
        recorder=StreamRecorder(repo / "runs"),
    )

    window = read_window(repo / "runs", 5)

    assert len(window) == 1
    assert not window[0].is_gap


def test_without_a_recorder_the_supervisor_writes_nothing(repo: Path) -> None:
    """One turn is one row. A supervisor governing one invocation inside a turn does not own it."""
    record = govern(QUICK, repo=repo, runs_dir=repo / "runs", run_id="r1", guard=guard(), turn_ceiling=5, verdict=lambda: Outcome.ADVANCED)

    assert record.outcome is Outcome.ADVANCED
    assert not (repo / "runs").exists()


def test_a_second_run_declines_to_start(tmp_path: Path) -> None:
    lock = tmp_path / "run.lock"
    with single_flight(lock), pytest.raises(LockBusy):
        with single_flight(lock):
            pytest.fail("the second holder must not acquire the lock")


def test_the_lock_is_released_afterwards(tmp_path: Path) -> None:
    lock = tmp_path / "run.lock"
    with single_flight(lock):
        pass
    with single_flight(lock):
        pass


def test_tree_is_dirty_reads_the_real_tree(repo: Path) -> None:
    assert tree_is_dirty(repo) is False
    (repo / "b.txt").write_text("x\n", encoding="utf-8")
    assert tree_is_dirty(repo) is True


def test_the_harness_own_stream_does_not_count_as_a_dirty_tree(repo: Path) -> None:
    """The supervisor writes a marker into the tree it is about to judge; unfiltered, every run reads dirty."""
    runs = repo / "runs"
    runs.mkdir()
    (runs / "20260816T200000Z-r1.start").write_text("{}", encoding="utf-8")

    assert tree_is_dirty(repo) is True
    assert tree_is_dirty(repo, ignore=runs) is False


def test_the_turn_ceiling_kill_records_its_own_reason(repo: Path) -> None:
    """The harness's own stops are the failures most likely to recur; they should be the most legible."""
    counter = iter(range(100))

    record = govern(
        SLEEPER,
        repo=repo,
        runs_dir=repo / "runs",
        run_id="r1",
        guard=guard(wall_clock_seconds=30),
        turn_ceiling=3,
        turns_taken=lambda: next(counter),
    )

    assert record.failure_kind is FailureKind.TURN_LIMIT
    assert record.enforced_by is EnforcedBy.HARNESS


def test_a_wall_clock_kill_carries_no_reason_because_the_union_has_none(repo: Path) -> None:
    """No tenth value is added for it; the note names the bound instead."""
    record = govern(SLEEPER, repo=repo, runs_dir=repo / "runs", run_id="r1", guard=guard(wall_clock_seconds=1), turn_ceiling=5)

    assert record.failure_kind is None
    assert "wall clock exceeded" in record.note


def test_an_agent_flushed_verdict_carries_no_harness_reason(repo: Path) -> None:
    """A reason is what the harness knows about its own stop; it says nothing about the agent's."""
    record = govern(
        QUICK, repo=repo, runs_dir=repo / "runs", run_id="r1", guard=guard(), turn_ceiling=5, verdict=lambda: Outcome.ADVANCED
    )

    assert record.failure_kind is None
