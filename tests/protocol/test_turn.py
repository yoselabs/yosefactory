"""The frozen surface: four outcomes, two writers, and the fields a public repo may not carry."""

from __future__ import annotations

import pytest

from yosefactory.protocol.turn import (
    CheckResult,
    EnforcedBy,
    Outcome,
    RecordError,
    TurnRecord,
    counts_as_progress,
    from_dict,
)


def a_record(**overrides: object) -> TurnRecord:
    base: dict[str, object] = {
        "run_id": "r1",
        "started_at": "2026-08-16T20:00:00+00:00",
        "ended_at": "2026-08-16T20:05:00+00:00",
        "outcome": Outcome.ADVANCED,
        "enforced_by": EnforcedBy.AGENT,
        "dirty": False,
        "isolated": True,
    }
    return TurnRecord(**{**base, **overrides})  # type: ignore[arg-type]


def test_outcome_has_exactly_four_values() -> None:
    assert [o.value for o in Outcome] == ["advanced", "blocked", "nothing-ready", "failed"]


def test_a_fifth_outcome_cannot_be_constructed() -> None:
    with pytest.raises(ValueError, match="stalled"):
        Outcome("stalled")


def test_unknown_outcome_is_rejected_by_name() -> None:
    payload = a_record().to_dict() | {"outcome": "succeeded"}
    with pytest.raises(RecordError, match="succeeded"):
        from_dict(payload)


@pytest.mark.parametrize("value", ["", None])
def test_missing_outcome_is_rejected(value: object) -> None:
    payload = a_record().to_dict()
    payload["outcome"] = value
    with pytest.raises(RecordError):
        from_dict(payload)


@pytest.mark.parametrize("field", ["enforced_by", "dirty", "isolated", "run_id", "started_at", "ended_at"])
def test_every_required_field_is_required(field: str) -> None:
    payload = a_record().to_dict()
    del payload[field]
    with pytest.raises(RecordError, match=field):
        from_dict(payload)


def test_flags_must_be_booleans_not_truthy_strings() -> None:
    payload = a_record().to_dict() | {"dirty": "yes"}
    with pytest.raises(RecordError, match="dirty"):
        from_dict(payload)


@pytest.mark.parametrize("leak", ["/Users/someone/Workspaces/x", "wrote /home/op/.claude", "/root/.codex"])
def test_home_rooted_paths_never_reach_a_record(leak: str) -> None:
    with pytest.raises(RecordError, match="public"):
        a_record(note=leak)


def test_a_relative_path_is_fine() -> None:
    assert a_record(note="wrote ledger/runs/x.json").note.startswith("wrote")


def test_nothing_ready_is_not_progress() -> None:
    assert counts_as_progress(Outcome.ADVANCED)
    assert not counts_as_progress(Outcome.NOTHING_READY)
    assert not counts_as_progress(Outcome.BLOCKED)
    assert not counts_as_progress(Outcome.FAILED)


def test_round_trip_preserves_every_field() -> None:
    record = a_record(outcome=Outcome.NOTHING_READY, enforced_by=EnforcedBy.HARNESS, dirty=True, isolated=False, note="n")
    assert from_dict(record.to_dict()) == record


def test_a_failed_check_must_say_what_it_saw() -> None:
    with pytest.raises(RecordError, match="what it observed"):
        CheckResult(name="tests", passed=False, detail="")
