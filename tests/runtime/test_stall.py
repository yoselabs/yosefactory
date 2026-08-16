"""Absence is the predicate. Every test here is a window with no errors in it that must still fire."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from yosefactory.protocol.turn import EnforcedBy, FailureKind, Outcome, TurnRecord
from yosefactory.runtime.runs import append, open_run
from yosefactory.runtime.stall import Status, detect, main


def write(runs: Path, minute: int, outcome: Outcome, *, kind: FailureKind | None = None) -> None:
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
            failure_kind=kind,
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


def test_a_wholly_starved_window_is_classified_starved(tmp_path: Path) -> None:
    write(tmp_path, 0, Outcome.FAILED, kind=FailureKind.BUDGET_EXHAUSTED)
    write(tmp_path, 1, Outcome.FAILED, kind=FailureKind.RATE_LIMIT)

    verdict = detect(tmp_path, window=2)

    assert verdict.status is Status.STARVED
    assert verdict.stalled


def test_starvation_still_exits_non_zero(tmp_path: Path) -> None:
    write(tmp_path, 0, Outcome.FAILED, kind=FailureKind.BUDGET_EXHAUSTED)
    assert main([str(tmp_path), "1"]) == 2


def test_starved_and_stalled_are_distinct_exit_codes(tmp_path: Path) -> None:
    starved_dir, broken_dir = tmp_path / "starved", tmp_path / "broken"
    write(starved_dir, 0, Outcome.FAILED, kind=FailureKind.BUDGET_EXHAUSTED)
    write(broken_dir, 0, Outcome.NOTHING_READY)

    assert main([str(starved_dir), "1"]) == 2
    assert main([str(broken_dir), "1"]) == 1
    assert main([str(starved_dir), "1"]) != main([str(broken_dir), "1"])


def test_one_crash_among_starved_turns_is_broken_not_starved(tmp_path: Path) -> None:
    """The broken thing is the actionable one."""
    write(tmp_path, 0, Outcome.FAILED, kind=FailureKind.BUDGET_EXHAUSTED)
    write(tmp_path, 1, Outcome.FAILED, kind=FailureKind.CRASH)

    assert detect(tmp_path, window=2).status is Status.STALLED


def test_a_gap_among_starved_turns_is_broken_not_starved(tmp_path: Path) -> None:
    """A position with no record has no reason and may not be excused as starvation."""
    write(tmp_path, 0, Outcome.FAILED, kind=FailureKind.BUDGET_EXHAUSTED)
    open_run(tmp_path, "vanished", datetime(2026, 8, 16, 20, 1, 0, tzinfo=UTC))

    assert detect(tmp_path, window=2).status is Status.STALLED


def test_idle_backlog_among_starved_turns_is_broken_not_starved(tmp_path: Path) -> None:
    """The factory was free to try and had nothing to do, which is a stall rather than starvation."""
    write(tmp_path, 0, Outcome.FAILED, kind=FailureKind.BUDGET_EXHAUSTED)
    write(tmp_path, 1, Outcome.NOTHING_READY)

    assert detect(tmp_path, window=2).status is Status.STALLED


def test_an_authentication_failure_is_broken_not_starved(tmp_path: Path) -> None:
    """It stops requests exactly as starvation does; only a human clears it."""
    write(tmp_path, 0, Outcome.FAILED, kind=FailureKind.AUTH)

    assert detect(tmp_path, window=1).status is Status.STALLED


def test_a_null_reason_is_not_excused_as_starvation(tmp_path: Path) -> None:
    """A failure with no recorded reason is the same evidentiary state as a gap."""
    write(tmp_path, 0, Outcome.FAILED)

    assert detect(tmp_path, window=1).status is Status.STALLED


def test_the_report_names_the_classification_and_the_reasons(tmp_path: Path) -> None:
    write(tmp_path, 0, Outcome.FAILED, kind=FailureKind.BUDGET_EXHAUSTED)
    write(tmp_path, 1, Outcome.FAILED, kind=FailureKind.RATE_LIMIT)

    report = detect(tmp_path, window=2).report()

    assert "STARVED" in report
    assert "budget_exhausted=1" in report
    assert "rate_limit=1" in report


def test_the_original_stalled_field_still_answers_either_alarm(tmp_path: Path) -> None:
    """Existing callers asking only `if verdict.stalled` see no behaviour change."""
    write(tmp_path, 0, Outcome.FAILED, kind=FailureKind.BUDGET_EXHAUSTED)
    assert detect(tmp_path, window=1).stalled is True
