"""The stream: append-only, gap-detecting, and blind to the hand-authored ledger rows by construction."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from yosefactory.protocol.turn import EnforcedBy, Outcome, TurnRecord
from yosefactory.runtime.runs import StreamError, append, open_run, read_window


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
