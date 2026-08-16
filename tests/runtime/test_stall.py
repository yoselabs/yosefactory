"""Absence is the predicate. Every test here is a window with no errors in it that must still fire."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from yosefactory.protocol.turn import EnforcedBy, Outcome, TurnRecord
from yosefactory.runtime.runs import append, open_run
from yosefactory.runtime.stall import detect, main


def write(runs: Path, minute: int, outcome: Outcome) -> None:
    started = datetime(2026, 8, 16, 20, minute, 0, tzinfo=UTC)
    slug = open_run(runs, f"r{minute}", started)
    append(
        runs,
        slug,
        TurnRecord(
            run_id=f"r{minute}",
            started_at=started.isoformat(),
            ended_at=started.isoformat(),
            outcome=outcome,
            enforced_by=EnforcedBy.AGENT,
            dirty=False,
            isolated=True,
        ),
    )


def test_a_window_of_nothing_ready_fires(tmp_path: Path) -> None:
    for minute in range(5):
        write(tmp_path, minute, Outcome.NOTHING_READY)
    assert detect(tmp_path, window=5).stalled


def test_a_window_of_blocked_fires(tmp_path: Path) -> None:
    for minute in range(5):
        write(tmp_path, minute, Outcome.BLOCKED)
    assert detect(tmp_path, window=5).stalled


def test_failures_mixed_with_nothing_ready_still_fire(tmp_path: Path) -> None:
    write(tmp_path, 0, Outcome.FAILED)
    write(tmp_path, 1, Outcome.NOTHING_READY)
    write(tmp_path, 2, Outcome.FAILED)
    assert detect(tmp_path, window=3).stalled


def test_one_advance_anywhere_in_the_window_clears_it(tmp_path: Path) -> None:
    write(tmp_path, 0, Outcome.NOTHING_READY)
    write(tmp_path, 1, Outcome.ADVANCED)
    write(tmp_path, 2, Outcome.NOTHING_READY)
    assert not detect(tmp_path, window=3).stalled


def test_an_advance_older_than_the_window_does_not_clear_it(tmp_path: Path) -> None:
    write(tmp_path, 0, Outcome.ADVANCED)
    for minute in range(1, 6):
        write(tmp_path, minute, Outcome.NOTHING_READY)

    verdict = detect(tmp_path, window=3)

    assert verdict.stalled
    assert verdict.last_advance is not None, "the alarm still reports where the last advance was"


def test_an_empty_stream_fires_rather_than_reporting_no_data(tmp_path: Path) -> None:
    verdict = detect(tmp_path, window=5)
    assert verdict.stalled
    assert verdict.examined == 0


def test_a_window_of_nothing_but_gaps_fires(tmp_path: Path) -> None:
    for minute in range(3):
        open_run(tmp_path, f"r{minute}", datetime(2026, 8, 16, 20, minute, 0, tzinfo=UTC))

    verdict = detect(tmp_path, window=3)

    assert verdict.stalled
    assert verdict.gaps == 3


def test_a_gap_counts_against_the_window_rather_than_narrowing_it(tmp_path: Path) -> None:
    write(tmp_path, 0, Outcome.ADVANCED)
    open_run(tmp_path, "vanished", datetime(2026, 8, 16, 20, 1, 0, tzinfo=UTC))
    open_run(tmp_path, "vanished2", datetime(2026, 8, 16, 20, 2, 0, tzinfo=UTC))

    verdict = detect(tmp_path, window=2)

    assert verdict.stalled, "the two most recent positions are gaps; the older advance is outside the window"
    assert verdict.examined == 2


def test_the_alarm_states_what_it_saw(tmp_path: Path) -> None:
    for minute in range(4):
        write(tmp_path, minute, Outcome.NOTHING_READY)

    report = detect(tmp_path, window=4).report()

    assert "STALLED" in report
    assert "window=4" in report
    assert "nothing-ready=4" in report
    assert "no advance anywhere in the stream" in report


def test_the_alarm_reports_the_age_of_the_last_advance(tmp_path: Path) -> None:
    write(tmp_path, 0, Outcome.ADVANCED)
    for minute in range(1, 5):
        write(tmp_path, minute, Outcome.NOTHING_READY)

    report = detect(tmp_path, window=3).report()

    assert "last advance at" in report


def test_a_stall_exits_non_zero_for_a_scheduler(tmp_path: Path) -> None:
    for minute in range(3):
        write(tmp_path, minute, Outcome.NOTHING_READY)
    assert main([str(tmp_path), "3"]) == 1


def test_a_healthy_stream_exits_zero(tmp_path: Path) -> None:
    write(tmp_path, 0, Outcome.ADVANCED)
    assert main([str(tmp_path), "3"]) == 0
