"""The frozen surface: four outcomes, two writers, and the fields a public repo may not carry."""

from __future__ import annotations

import pytest

from yosefactory.protocol.turn import (
    STARVATION,
    BlockedKind,
    CheckResult,
    EnforcedBy,
    FailureKind,
    Outcome,
    RecordError,
    TurnRecord,
    counts_as_progress,
    from_dict,
    resumable,
    starved,
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


def test_starved_and_broken_are_distinguishable_without_reading_free_text() -> None:
    """architecture.md §7b rule 3: rate_limit may never fold into a generic failure.

    The model draws from the same rolling window as Denis's own interactive use, so one of these
    waits and the other gets fixed.
    """
    starved = a_record(outcome=Outcome.FAILED, failure_kind=FailureKind.RATE_LIMIT)
    broken = a_record(outcome=Outcome.FAILED, failure_kind=FailureKind.CRASH)

    assert starved.outcome is broken.outcome
    assert starved.to_dict()["failure_kind"] == "rate_limit"
    assert broken.to_dict()["failure_kind"] == "crash"


def test_a_run_level_stop_is_a_failure_kind_too() -> None:
    """`budget_exhausted` narrows to `failed` carrying no typed kind of its own, so it needs one."""
    assert a_record(outcome=Outcome.FAILED, failure_kind=FailureKind.BUDGET_EXHAUSTED).failure_kind is FailureKind.BUDGET_EXHAUSTED


@pytest.mark.parametrize("outcome", [Outcome.ADVANCED, Outcome.BLOCKED, Outcome.NOTHING_READY])
def test_a_failure_kind_on_anything_but_failed_is_rejected(outcome: Outcome) -> None:
    with pytest.raises(RecordError, match=r"failure_kind 'crash' on outcome"):
        a_record(outcome=outcome, failure_kind=FailureKind.CRASH)


def test_a_failure_kind_outside_the_set_is_rejected() -> None:
    with pytest.raises(RecordError, match="failure_kind must be one of"):
        a_record(outcome=Outcome.FAILED, failure_kind="quota")


def test_a_harness_kill_needs_no_failure_kind() -> None:
    """A supervisor writing for a process it killed has no executor reason; `enforced_by` says who."""
    record = a_record(outcome=Outcome.FAILED, enforced_by=EnforcedBy.HARNESS)

    assert record.failure_kind is None
    assert record.to_dict()["failure_kind"] is None


def test_a_record_written_before_the_field_still_reads() -> None:
    payload = a_record(outcome=Outcome.FAILED).to_dict()
    del payload["failure_kind"]

    assert from_dict(payload).failure_kind is None


def test_an_unknown_failure_kind_in_a_payload_is_rejected_by_name() -> None:
    payload = {**a_record(outcome=Outcome.FAILED).to_dict(), "failure_kind": "quota"}

    with pytest.raises(RecordError, match=r"unknown failure_kind 'quota'"):
        from_dict(payload)


def test_a_failure_kind_round_trips() -> None:
    record = a_record(outcome=Outcome.FAILED, failure_kind=FailureKind.AUTH)

    assert from_dict(record.to_dict()) == record


def test_a_wait_is_distinguishable_from_a_dead_end() -> None:
    """One of these clears when something arrives; nothing arrives that changes the other."""
    waiting = a_record(outcome=Outcome.BLOCKED, blocked_kind=BlockedKind.AWAITING)
    dead_end = a_record(outcome=Outcome.BLOCKED, blocked_kind=BlockedKind.REFUSED)

    assert waiting.outcome is dead_end.outcome
    assert resumable(waiting.blocked_kind) is True
    assert resumable(dead_end.blocked_kind) is False


def test_resumability_is_unknown_rather_than_either_answer_when_the_kind_is_null() -> None:
    """A binary predicate would have to fold this into a wait or a dead end, and both are lies."""
    assert resumable(a_record(outcome=Outcome.BLOCKED).blocked_kind) is None


def test_a_denied_tool_is_resumable_and_a_refusal_is_not() -> None:
    assert resumable(BlockedKind.NEEDS_APPROVAL) is True
    assert resumable(BlockedKind.REFUSED) is False


@pytest.mark.parametrize("outcome", [Outcome.ADVANCED, Outcome.NOTHING_READY, Outcome.FAILED])
def test_a_blocked_kind_on_anything_but_blocked_is_rejected(outcome: Outcome) -> None:
    with pytest.raises(RecordError, match=r"blocked_kind 'refused' on outcome"):
        a_record(outcome=outcome, blocked_kind=BlockedKind.REFUSED)


def test_a_blocked_kind_outside_the_set_is_rejected() -> None:
    with pytest.raises(RecordError, match="blocked_kind must be one of"):
        a_record(outcome=Outcome.BLOCKED, blocked_kind="stuck")


def test_an_unknown_blocked_kind_in_a_payload_is_rejected_by_name() -> None:
    payload = {**a_record(outcome=Outcome.BLOCKED).to_dict(), "blocked_kind": "stuck"}

    with pytest.raises(RecordError, match=r"unknown blocked_kind 'stuck'"):
        from_dict(payload)


def test_a_blocked_record_written_before_the_field_still_reads() -> None:
    payload = a_record(outcome=Outcome.BLOCKED).to_dict()
    del payload["blocked_kind"]
    record = from_dict(payload)

    assert record.blocked_kind is None
    assert resumable(record.blocked_kind) is None


def test_a_blocked_kind_round_trips() -> None:
    record = a_record(outcome=Outcome.BLOCKED, blocked_kind=BlockedKind.NEEDS_APPROVAL)

    assert from_dict(record.to_dict()) == record


def test_the_two_reason_axes_cannot_collide() -> None:
    """Neither field can appear beside the other, because no record carries both outcomes."""
    with pytest.raises(RecordError, match="on outcome 'blocked'"):
        a_record(outcome=Outcome.BLOCKED, blocked_kind=BlockedKind.AWAITING, failure_kind=FailureKind.CRASH)


def test_every_executor_outcome_that_blocks_can_say_why() -> None:
    """A new vendor stop reason narrowing to `blocked` must break this rather than reopen the collapse.

    The failure-kind detector next to this one earns its place on a near-miss: assembling that set
    from the executor's typed failures alone would have dropped `budget_exhausted`. Same risk here.
    """
    from yosefactory.executor.outcome import _TO_PROTOCOL, RunOutcome

    blocking = {outcome for outcome, narrowed in _TO_PROTOCOL.items() if narrowed is Outcome.BLOCKED}
    recordable = {kind.value for kind in BlockedKind}

    assert blocking == {RunOutcome.NEEDS_APPROVAL, RunOutcome.REFUSED}
    assert {outcome.value for outcome in blocking} <= recordable


def test_every_executor_failure_kind_can_be_recorded() -> None:
    """A new vendor reason must break this test rather than become an unrecordable record.

    The executor's two failing vocabularies flatten onto one question here — its run-level stops that
    narrow to `failed`, and its typed failure kinds — so both are checked.
    """
    from yosefactory.executor.outcome import FailureKind as ExecutorFailureKind
    from yosefactory.executor.outcome import RunOutcome

    recordable = {kind.value for kind in FailureKind}

    assert {kind.value for kind in ExecutorFailureKind} <= recordable
    narrowing_to_failed = {RunOutcome.BUDGET_EXHAUSTED, RunOutcome.TURN_LIMIT, RunOutcome.CANCELLED}
    assert {outcome.value for outcome in narrowing_to_failed} <= recordable


def test_starvation_and_breakage_partition_every_failure_kind() -> None:
    """A tenth kind fails this rather than defaulting into breakage.

    Silent default is the safe direction for an alarm and the wrong one for evidence: it would
    manufacture agreement between a value nobody classified and a classification nobody chose.
    """
    starving = {kind for kind in FailureKind if starved(kind)}
    breaking = {kind for kind in FailureKind if starved(kind) is False}

    assert starving == STARVATION
    assert starving | breaking == set(FailureKind)
    assert not starving & breaking


def test_authentication_is_breakage_not_starvation() -> None:
    """It stops requests exactly as an exhausted quota does, and only a human clears it.

    Filed as starvation, the alarm would tell the operator to wait out the one failure they must
    act on.
    """
    assert starved(FailureKind.AUTH) is False
    assert starved(FailureKind.RATE_LIMIT) is True
    assert starved(FailureKind.BUDGET_EXHAUSTED) is True


def test_an_unrecorded_reason_is_not_a_claim_that_it_was_not_starvation() -> None:
    """Absent is its own answer. A caller that must act anyway owns the direction it errs in."""
    assert starved(None) is None
    assert starved(a_record(outcome=Outcome.FAILED).failure_kind) is None


def test_a_starved_record_is_still_a_failure() -> None:
    """Starvation renames a failure; it never makes one into progress."""
    record = a_record(outcome=Outcome.FAILED, failure_kind=FailureKind.BUDGET_EXHAUSTED)

    assert starved(record.failure_kind) is True
    assert not counts_as_progress(record.outcome)
