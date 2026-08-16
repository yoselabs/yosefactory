"""The record one run of the factory leaves behind, and the four words it is allowed to end in.

Frozen because every row ever written is compared against every other row. The item states in
`backlog` are a different axis and share three spellings with `Outcome` by coincidence: an item is
`blocked` for as long as something blocks it, a *turn* is `blocked` for the one turn that hit it.

`outcome` is one axis and the reason fields beside it are another. The first is exactly four words
and is frozen; `failure_kind` says why a failure happened and `blocked_kind` says what a block is
waiting on, both shaped by whichever executor ran and both expected to change. Widening `outcome` to
carry either would conflate *did this advance* with *why did it stop* and cost the four-value
contract that governing decisions are typed against.

Two nullable reason fields, each valid for exactly one outcome, is one short of a pattern worth
collapsing into a single field whose vocabulary depends on `outcome`. Two closed sets validate
independently and a value means something without consulting `outcome` first, so they stay separate
until a third outcome earns a typed reason — the candidate being *why was nothing ready* — at which
point all three unify and the migration is paid once.

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


class BlockedKind(StrEnum):
    """What a blocked turn is waiting on. A second axis over `Outcome`, never a widening of it.

    Three facts narrowed to the single word `blocked` before this existed: an item that entered
    `blocked` awaiting something, an agent denied a tool it asked for, and an agent that declined the
    work. The first two are resumable and the third is not, so a reader of `outcome` alone cannot
    tell *wait* from *this will never move*.

    **These are not item states, and the reason is that nothing would write them.** A refusal is a
    fact about one executor invocation, not a place an item sits — the item is still `doing` when the
    agent declines. A state needs a writer or the same fact has two representations, which is the
    argument that keeps `terminal` a predicate rather than a state (architecture.md §3).

    `awaiting` names where the detail is rather than copying it: the item's own `awaiting` object
    holds the block's `kind`, `ref`, deadline and timeout policy.
    """

    AWAITING = "awaiting"
    NEEDS_APPROVAL = "needs_approval"
    REFUSED = "refused"


class EnforcedBy(StrEnum):
    """Who authored the verdict. A killed process writes nothing, so the supervisor writes for it."""

    AGENT = "agent"
    HARNESS = "harness"


# A run may be terminated mid-edit, so the supervisor computes `dirty` after the process is gone and
# the agent never supplies it. Kept as a name rather than a comment because both writers construct
# records and only one of them is allowed to claim this field is meaningful.
SUPERVISOR_OWNED: Final = ("dirty",)

# The kinds that mean the factory was prevented from trying rather than broken by trying. Everything
# else is breakage, including `auth`: an expired credential stops requests exactly as an exhausted
# quota does and is cleared only by a human, so classifying it as starvation would tell the operator
# to wait out the one failure they must act on.
STARVATION: Final = frozenset({FailureKind.RATE_LIMIT, FailureKind.BUDGET_EXHAUSTED})

# The kinds something can arrive to clear. `refused` is absent by design: nothing arrives that
# changes a refusal, and the answer to one is a human re-deciding the goal — D019's falsify-and-
# succeed rather than a resumption. `needs_approval` is here and is nonetheless unbounded, because a
# permission denial writes no question and so acquires no deadline and nothing sweeps it; that
# violates S172 and violated it before this set existed.
RESUMABLE: Final = frozenset({BlockedKind.AWAITING, BlockedKind.NEEDS_APPROVAL})

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


def _check_reason(value: Any, vocabulary: type[StrEnum], field_name: str, only_for: Outcome, outcome: Outcome) -> None:
    """A reason field is drawn from its own closed set and says nothing on any other outcome."""
    if value is None:
        return
    if not isinstance(value, vocabulary):
        raise RecordError(f"{field_name} must be one of {[member.value for member in vocabulary]}, got {value!r}")
    if outcome is not only_for:
        raise RecordError(
            f"{field_name} {value.value!r} on outcome {outcome.value!r}; "
            f"only {only_for.value!r} has a reason to give"
        )


def _read_reason(payload: dict[str, Any], vocabulary: type[StrEnum], field_name: str) -> Any:
    """A missing key is null rather than an error: records predate every field that was added."""
    raw = payload.get(field_name)
    if raw is None:
        return None
    try:
        return vocabulary(raw)
    except ValueError as exc:
        valid = [member.value for member in vocabulary]
        raise RecordError(f"unknown {field_name} {raw!r}; valid: {valid}") from exc


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
    # Null here means the writer gave no reason, never that the block is resumable or that it is not.
    blocked_kind: BlockedKind | None = None

    def __post_init__(self) -> None:
        if not self.run_id:
            raise RecordError("a turn record must carry a run_id")
        if not isinstance(self.outcome, Outcome):
            raise RecordError(f"outcome must be one of {[o.value for o in Outcome]}, got {self.outcome!r}")
        if not isinstance(self.enforced_by, EnforcedBy):
            raise RecordError(f"enforced_by must be one of {[e.value for e in EnforcedBy]}, got {self.enforced_by!r}")
        _check_reason(self.failure_kind, FailureKind, "failure_kind", Outcome.FAILED, self.outcome)
        _check_reason(self.blocked_kind, BlockedKind, "blocked_kind", Outcome.BLOCKED, self.outcome)
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
            "blocked_kind": self.blocked_kind.value if self.blocked_kind is not None else None,
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
    failure_kind = _read_reason(payload, FailureKind, "failure_kind")
    blocked_kind = _read_reason(payload, BlockedKind, "blocked_kind")
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
        blocked_kind=blocked_kind,
    )


def counts_as_progress(outcome: Outcome) -> bool:
    """The single place progress is defined. `nothing-ready` and `blocked` are not it."""
    return outcome is Outcome.ADVANCED


def starved(kind: FailureKind | None) -> bool | None:
    """Whether a failure means the factory was prevented from trying. `None` when the record does not
    say.

    The single place starvation is defined, for the same reason `counts_as_progress` and `resumable`
    are: a starved factory waits and a broken one gets fixed, and two readers disagreeing about which
    is which is the failure this distinction exists to prevent.

    Tri-state on the same argument as `resumable`, and it costs a caller something here, which is
    why it is worth stating. Folding an absent kind into `False` would read as *we know this is not
    starvation* — a fact no writer supplied. An absent reason and an absent record say the same
    thing, which is nothing, and a caller that must act anyway owns the direction it errs in rather
    than inheriting one from this function.
    """
    if kind is None:
        return None
    return kind in STARVATION


def resumable(kind: BlockedKind | None) -> bool | None:
    """Whether something can arrive that clears the block. `None` when the record does not say.

    The single place resumability is defined, for the same reason `counts_as_progress` is: a planner
    and a stall detector reading one word differently is the failure this field exists to prevent.

    Derived and never stored — a boolean beside the kind is two representations of one fact, and the
    copy that drifts is the one the detector reads. Tri-state on purpose: folding an absent kind into
    either answer manufactures a fact a caller would act on, so a caller must handle all three.
    """
    if kind is None:
        return None
    return kind in RESUMABLE
