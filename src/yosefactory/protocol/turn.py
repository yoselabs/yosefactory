"""The record one run of the factory leaves behind, and the four words it is allowed to end in.

Frozen because every row ever written is compared against every other row. The item states in
`backlog` are a different axis and share three spellings with `Outcome` by coincidence: an item is
`blocked` for as long as something blocks it, a *turn* is `blocked` for the one turn that hit it.

`outcome` and `failure_kind` are two axes and not one field. The first is exactly four words and is
frozen; the second says why a failure happened, is shaped by whichever executor ran, and is expected
to change. Widening the first to carry the second would conflate *did this advance* with *why did it
break* and cost the four-value contract that governing decisions are typed against.

`nothing-ready` is not success. Nothing in this package may treat it as one — the failure this
record exists to make visible is a long run of green turns that produced nothing, and a reader that
scores green as healthy cannot see it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Final, Protocol, runtime_checkable


class RecordError(ValueError):
    """A turn record that may not be written."""


class Outcome(StrEnum):
    """What a turn amounted to. Exactly four, and `ADVANCED` is the only one that is output."""

    ADVANCED = "advanced"
    BLOCKED = "blocked"
    NOTHING_READY = "nothing-ready"
    FAILED = "failed"


class FailureKind(StrEnum):
    """Why a turn failed. A second axis over `Outcome`, never a widening of it.

    `Outcome` answers *did the turn advance* and is frozen because every row is compared against
    every other row. This answers *why did it fail*, is shaped by whatever executor ran, and is
    expected to change as vendors do — soft by the same test that freezes the other.

    The values flatten the executor's two failing vocabularies onto the one question. Its run-level
    stops (`budget_exhausted`, `turn_limit`, `cancelled`) all narrow to `FAILED` carrying no reason
    of their own, so a set mirroring only its typed failure kinds would still leave a starved run
    indistinguishable from a broken one. The names of the two vocabularies are disjoint, so a reader
    never has to know which level a value came from.

    `rate_limit` is the one that may never fold into a generic failure — architecture.md §7b rule 3.
    The model draws from the same rolling window as the operator's own interactive use, so a factory
    starved of quota waits and a factory whose model is broken gets fixed.
    """

    BUDGET_EXHAUSTED = "budget_exhausted"
    TURN_LIMIT = "turn_limit"
    CANCELLED = "cancelled"
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    CRASH = "crash"
    BAD_OUTPUT = "bad_output"
    TASK_ERROR = "task_error"
    VERSION_MISMATCH = "version_mismatch"


class EnforcedBy(StrEnum):
    """Who authored the verdict. A killed process writes nothing, so the supervisor writes for it."""

    AGENT = "agent"
    HARNESS = "harness"


# A run may be terminated mid-edit, so the supervisor computes `dirty` after the process is gone and
# the agent never supplies it. Kept as a name rather than a comment because both writers construct
# records and only one of them is allowed to claim this field is meaningful.
SUPERVISOR_OWNED: Final = ("dirty",)

# This repository is public and the stream is committed. Home-rooted absolute paths identify the
# machine, so they never reach a record — caught at write time rather than at review time.
_HOME_ROOTED: Final = re.compile(r"(?:^|[\s\"'=(,:])(/Users/|/home/|/root(?:/|\b))")

_REQUIRED: Final = ("run_id", "started_at", "ended_at", "outcome", "enforced_by", "dirty", "isolated")


@runtime_checkable
class IndependentCheck(Protocol):
    """I9: a check performed by an actor other than the one that did the work.

    Signature only. The checks themselves are runtime concerns and live there — what belongs in the
    protocol is that a `done` transition has a shape which cannot be satisfied by a self-report.
    """

    name: str

    def __call__(self) -> CheckResult: ...


@dataclass(frozen=True, slots=True)
class CheckResult:
    """What an independent check observed. `passed` alone is never enough to act on — see `detail`."""

    name: str
    passed: bool
    detail: str

    def __post_init__(self) -> None:
        if not self.name:
            raise RecordError("a check result must name its check")
        if not self.passed and not self.detail:
            raise RecordError(f"check {self.name!r} failed without saying what it observed")


@dataclass(frozen=True, slots=True)
class TurnRecord:
    """One turn, as it will be read months later by something that was not there."""

    run_id: str
    started_at: str
    ended_at: str
    outcome: Outcome
    enforced_by: EnforcedBy
    dirty: bool
    isolated: bool
    note: str = ""
    # Null is a real value, not a gap: a supervisor writing for a process it killed has no executor
    # reason to give, and `enforced_by` already says who ended the run.
    failure_kind: FailureKind | None = None

    def __post_init__(self) -> None:
        if not self.run_id:
            raise RecordError("a turn record must carry a run_id")
        if not isinstance(self.outcome, Outcome):
            raise RecordError(f"outcome must be one of {[o.value for o in Outcome]}, got {self.outcome!r}")
        if not isinstance(self.enforced_by, EnforcedBy):
            raise RecordError(f"enforced_by must be one of {[e.value for e in EnforcedBy]}, got {self.enforced_by!r}")
        if self.failure_kind is not None:
            if not isinstance(self.failure_kind, FailureKind):
                raise RecordError(f"failure_kind must be one of {[k.value for k in FailureKind]}, got {self.failure_kind!r}")
            if self.outcome is not Outcome.FAILED:
                raise RecordError(
                    f"failure_kind {self.failure_kind.value!r} on outcome {self.outcome.value!r}; "
                    f"only {Outcome.FAILED.value!r} has a reason to give"
                )
        for field_name in ("started_at", "ended_at"):
            if not getattr(self, field_name):
                raise RecordError(f"a turn record must carry {field_name}")
        for field_name in ("run_id", "started_at", "ended_at", "note"):
            value = getattr(self, field_name)
            if _HOME_ROOTED.search(value):
                raise RecordError(f"{field_name} carries a home-rooted absolute path; this repository is public")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "outcome": self.outcome.value,
            "enforced_by": self.enforced_by.value,
            "dirty": self.dirty,
            "isolated": self.isolated,
            "note": self.note,
            "failure_kind": self.failure_kind.value if self.failure_kind is not None else None,
        }

    def with_note(self, note: str) -> TurnRecord:
        return replace(self, note=note)


def from_dict(payload: Any) -> TurnRecord:
    """Rebuild a record, rejecting anything the writer would not have been allowed to write."""
    if not isinstance(payload, dict):
        raise RecordError(f"a turn record must be a mapping, got {type(payload).__name__}")
    missing = [key for key in _REQUIRED if key not in payload or payload[key] == ""]
    if missing:
        raise RecordError(f"turn record is missing required field(s): {', '.join(missing)}")
    try:
        outcome = Outcome(payload["outcome"])
    except ValueError as exc:
        raise RecordError(f"unknown outcome {payload['outcome']!r}; valid: {[o.value for o in Outcome]}") from exc
    try:
        enforced_by = EnforcedBy(payload["enforced_by"])
    except ValueError as exc:
        raise RecordError(f"unknown enforced_by {payload['enforced_by']!r}; valid: {[e.value for e in EnforcedBy]}") from exc
    raw_kind = payload.get("failure_kind")
    try:
        failure_kind = FailureKind(raw_kind) if raw_kind is not None else None
    except ValueError as exc:
        raise RecordError(f"unknown failure_kind {raw_kind!r}; valid: {[k.value for k in FailureKind]}") from exc
    for flag in ("dirty", "isolated"):
        if not isinstance(payload[flag], bool):
            raise RecordError(f"{flag} must be a boolean, got {payload[flag]!r}")
    return TurnRecord(
        run_id=str(payload["run_id"]),
        started_at=str(payload["started_at"]),
        ended_at=str(payload["ended_at"]),
        outcome=outcome,
        enforced_by=enforced_by,
        dirty=payload["dirty"],
        isolated=payload["isolated"],
        note=str(payload.get("note", "")),
        failure_kind=failure_kind,
    )


def counts_as_progress(outcome: Outcome) -> bool:
    """The single place progress is defined. `nothing-ready` and `blocked` are not it."""
    return outcome is Outcome.ADVANCED
