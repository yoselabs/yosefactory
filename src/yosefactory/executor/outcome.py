"""What one executor invocation amounted to, and how it narrows to the four words a record holds.

Two vocabularies, deliberately. `protocol.Outcome` answers *did the turn advance* and is frozen
because every row ever written is compared against every other one. This one answers *what did the
executor do*, changes as vendors change, and is therefore soft by the same test that freezes the
other.

The narrowing loses information on purpose, with one exception that is not allowed to be lost: a
factory starved of quota must never read as a broken model, and a run stopped by a permission denial
or a refusal must never read as one that broke. Both survive as a typed field on the turn record —
`failure_kind` for the first, `blocked_kind` for the second — derived here, beside `protocol_outcome`,
because the executor is what knows which of its endings means which.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from yosefactory.protocol.turn import BlockedKind, Outcome


class RunOutcome(StrEnum):
    """Names follow ACP's `stopReason`, so adopting ACP later is the identity mapping."""

    SUCCESS = "success"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TURN_LIMIT = "turn_limit"
    NEEDS_APPROVAL = "needs_approval"
    REFUSED = "refused"
    CANCELLED = "cancelled"
    FAILED = "failed"


class FailureKind(StrEnum):
    """Why a run failed, kept separate from whether it advanced. Two axes, never one field."""

    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    CRASH = "crash"
    BAD_OUTPUT = "bad_output"
    TASK_ERROR = "task_error"
    VERSION_MISMATCH = "version_mismatch"


# The executor cannot emit `nothing-ready`: whether there was work to do is a judgement about the
# backlog, made before an executor is ever started. Naming the exclusion keeps a later reader from
# adding a branch for it.
_TO_PROTOCOL: dict[RunOutcome, Outcome] = {
    RunOutcome.SUCCESS: Outcome.ADVANCED,
    RunOutcome.NEEDS_APPROVAL: Outcome.BLOCKED,
    RunOutcome.REFUSED: Outcome.BLOCKED,
    RunOutcome.BUDGET_EXHAUSTED: Outcome.FAILED,
    RunOutcome.TURN_LIMIT: Outcome.FAILED,
    RunOutcome.CANCELLED: Outcome.FAILED,
    RunOutcome.FAILED: Outcome.FAILED,
}

# The other half of the same narrowing, for the two endings `_TO_PROTOCOL` sends to `BLOCKED`. Kept
# as its own total mapping rather than a branch in the property below, so a new `RunOutcome` that
# ought to carry a blocked kind cannot be added to one dict and forgotten in the other — the test
# that checks both mappings agree would have nothing to check against.
_TO_BLOCKED_KIND: dict[RunOutcome, BlockedKind | None] = {
    RunOutcome.SUCCESS: None,
    RunOutcome.NEEDS_APPROVAL: BlockedKind.NEEDS_APPROVAL,
    RunOutcome.REFUSED: BlockedKind.REFUSED,
    RunOutcome.BUDGET_EXHAUSTED: None,
    RunOutcome.TURN_LIMIT: None,
    RunOutcome.CANCELLED: None,
    RunOutcome.FAILED: None,
}


@dataclass(frozen=True, slots=True)
class Usage:
    """Cost is recorded, never enforced: usage credits are off, so exhaustion stops requests."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    total_cost_usd: float = 0.0
    num_turns: int = 0


@dataclass(frozen=True, slots=True)
class RunResult:
    """`exit_code` is evidence and is never consulted to decide `outcome`."""

    outcome: RunOutcome
    usage: Usage
    transcript_path: Path
    exit_code: int | None
    dirty: bool
    failure_kind: FailureKind | None = None
    detail: str = ""

    @property
    def protocol_outcome(self) -> Outcome:
        return _TO_PROTOCOL[self.outcome]

    @property
    def blocked_kind(self) -> BlockedKind | None:
        """Which of the two blocking endings this is, or `None` for every other outcome.

        Derived from `outcome` rather than stored, on the same argument as `protocol_outcome`: the
        executor is the one component that knows what its own ending means, so the mapping lives here
        rather than being reconstructed by whoever writes the record.
        """
        return _TO_BLOCKED_KIND[self.outcome]
