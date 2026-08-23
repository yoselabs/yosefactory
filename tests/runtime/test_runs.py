"""The stream: append-only, gap-detecting, and blind to the hand-authored ledger rows by construction."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from yosefactory.protocol.turn import EnforcedBy, Outcome, TurnRecord
from yosefactory.runtime.runs import StreamError, append, ensure_transcripts_ignored, open_run, read_window


def git(repo: Path, *args: str) -> str:
    binary = shutil.which("git")
    assert binary is not None
    completed = subprocess.run([binary, *args], cwd=repo, capture_output=True, text=True, check=True)  # noqa: S603
    return completed.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.invalid")
    git(root, "config", "user.name", "T")
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(root, "add", "seed.txt")
    git(root, "commit", "-q", "-m", "seed")
    return root


def record(run_id: str, outcome: Outcome = Outcome.ADVANCED) -> TurnRecord:
    return TurnRecord(
        run_id=run_id,
        started_at="2026-08-16T20:00:00+00:00",
        ended_at="2026-08-16T20:01:00+00:00",
        outcome=outcome,
        enforced_by=EnforcedBy.AGENT,
        dirty=False,
        isolated=True,
    )


def at(minute: int) -> datetime:
    return datetime(2026, 8, 16, 20, minute, 0, tzinfo=UTC)


def test_a_record_is_never_rewritten(tmp_path: Path) -> None:
    slug = open_run(tmp_path, "r1", at(0))
    append(tmp_path, slug, record("r1"))
    with pytest.raises(StreamError, match="never rewritten"):
        append(tmp_path, slug, record("r1"))


def test_an_orphan_marker_is_a_gap_not_a_skipped_position(tmp_path: Path) -> None:
    open_run(tmp_path, "vanished", at(0))
    slug = open_run(tmp_path, "finished", at(1))
    append(tmp_path, slug, record("finished"))

    window = read_window(tmp_path, 5)

    assert [p.is_gap for p in window] == [True, False]
    assert window[0].outcome is Outcome.FAILED


def test_a_satisfied_marker_is_not_a_gap(tmp_path: Path) -> None:
    slug = open_run(tmp_path, "r1", at(0))
    append(tmp_path, slug, record("r1"))
    assert read_window(tmp_path, 5)[0].is_gap is False


def test_window_returns_the_most_recent_positions_oldest_first(tmp_path: Path) -> None:
    for minute in range(5):
        slug = open_run(tmp_path, f"r{minute}", at(minute))
        append(tmp_path, slug, record(f"r{minute}"))

    window = read_window(tmp_path, 3)

    assert [p.record.run_id for p in window if p.record] == ["r2", "r3", "r4"]


def test_the_hand_authored_ledger_rows_are_out_of_scope_by_construction(tmp_path: Path) -> None:
    """Not by a skip-list. The reader is pointed at its own directory and cannot see them at all."""
    ledger = tmp_path / "ledger"
    runs = ledger / "runs"
    ledger.mkdir()
    legacy = ledger / "0001-workflow-a.toml"
    legacy.write_text('seq = 1\noutcome = "T17 not settled, leans against"\n', encoding="utf-8")
    slug = open_run(runs, "r1", at(0))
    append(runs, slug, record("r1"))

    window = read_window(runs, 10)

    assert len(window) == 1
    assert legacy.read_text(encoding="utf-8").startswith("seq = 1")


def test_two_runs_finishing_together_produce_two_records(tmp_path: Path) -> None:
    first = open_run(tmp_path, "a", at(0))
    second = open_run(tmp_path, "b", at(0))
    append(tmp_path, first, record("a"))
    append(tmp_path, second, record("b"))

    assert sorted(p.record.run_id for p in read_window(tmp_path, 10) if p.record) == ["a", "b"]


def test_opening_the_same_run_twice_is_refused(tmp_path: Path) -> None:
    open_run(tmp_path, "r1", at(0))
    with pytest.raises(StreamError, match="already open"):
        open_run(tmp_path, "r1", at(0))


def test_an_unreadable_record_is_an_error_not_a_silent_skip(tmp_path: Path) -> None:
    slug = open_run(tmp_path, "r1", at(0))
    (tmp_path / f"{slug}.json").write_text(json.dumps({"run_id": "r1"}), encoding="utf-8")
    with pytest.raises(StreamError, match="not a readable turn record"):
        read_window(tmp_path, 5)


def test_an_absent_stream_reads_as_empty(tmp_path: Path) -> None:
    assert read_window(tmp_path / "nope", 5) == []


def test_a_transcript_written_after_the_guard_does_not_dirty_the_tree(repo: Path) -> None:
    """S237's regression, at the unit level: the failing case before this fix existed."""
    runs_dir = repo / "ledger" / "runs"
    ensure_transcripts_ignored(runs_dir, repo)
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / "turn-x.stream.jsonl").write_text("{}\n", encoding="utf-8")

    assert git(repo, "status", "--porcelain") == ""


def test_the_guard_still_lets_tracked_ledger_files_through(repo: Path) -> None:
    """The failure mode this must not reintroduce: ignoring the whole directory would swallow the
    `.start`/`.json`/`.wake.json` files `take_turn` actually commits (S237's second trail entry)."""
    runs_dir = repo / "ledger" / "runs"
    ensure_transcripts_ignored(runs_dir, repo)
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / "turn-x.start").write_text("{}\n", encoding="utf-8")

    status = git(repo, "status", "--porcelain", "--untracked-files=all")
    assert "turn-x.start" in status


def test_the_guard_is_idempotent(repo: Path) -> None:
    runs_dir = repo / "ledger" / "runs"
    ensure_transcripts_ignored(runs_dir, repo)
    ensure_transcripts_ignored(runs_dir, repo)

    exclude = repo / ".git" / "info" / "exclude"
    lines = exclude.read_text(encoding="utf-8").splitlines()
    assert lines.count("/ledger/runs/*.stream.jsonl") == 1


def test_the_guard_is_a_noop_when_the_ledger_lives_outside_the_workspace(tmp_path: Path) -> None:
    """The cross-repository shape (D026): nothing here is needed, and nothing here should write."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    foreign_ledger = tmp_path / "queue" / "ledger" / "runs"

    ensure_transcripts_ignored(foreign_ledger, workspace)

    assert not (workspace / ".git").exists()


def test_the_guard_is_a_noop_outside_a_git_worktree(tmp_path: Path) -> None:
    workspace = tmp_path / "plain"
    workspace.mkdir()
    runs_dir = workspace / "ledger" / "runs"

    ensure_transcripts_ignored(runs_dir, workspace)

    assert not (workspace / ".git").exists()
