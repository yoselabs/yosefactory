"""BlockReason sum type — structured replacement for free-form block strings.

Today the engine's reason for blocking a ticket lives as a plain string
built inline at each call site (``pipeline/breakers.py``,
``pipeline/preflight.py``, ``pipeline/stage_run.py``,
``adapters/git/local.py``). String-building at the call site hides the
reason shape and makes rendering subscribers (issue comments vs logs
vs MLflow metrics) duplicate formatting.

This ADT names the known block kinds and exposes ``.as_comment()`` so
progress subscribers render uniform messages. P1 lands the type; no
call sites adopt it yet — P4 (pipe-and-filter) migrates gating to
produce these.

The ``Generic(message)`` variant is the escape hatch for reasons not
yet classified. Every new ``Generic`` usage is an opportunity to
promote a new structured variant.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ReviewCyclesExceeded(BaseModel):
    """REVIEW stage looped more than ``max_review_cycles`` times."""

    kind: Literal["review_cycles_exceeded"] = "review_cycles_exceeded"
    cycles: int
    maximum: int

    def as_comment(self) -> str:
        return (
            f"Circuit breaker: {self.cycles} review cycles "
            f"exceeded max ({self.maximum})"
        )


class CostCeilingExceeded(BaseModel):
    """Accumulated per-ticket spend hit the configured ceiling."""

    kind: Literal["cost_ceiling_exceeded"] = "cost_ceiling_exceeded"
    spent_usd: float
    ceiling_usd: float

    def as_comment(self) -> str:
        return (
            f"Cost ceiling: ${self.spent_usd:.2f} >= "
            f"${self.ceiling_usd:.2f} per-ticket max"
        )


class MergeConflict(BaseModel):
    """Git merge with base branch produced a conflict."""

    kind: Literal["merge_conflict"] = "merge_conflict"
    base_branch: str

    def as_comment(self) -> str:
        return f"merge conflict with {self.base_branch}"


class GitCheckoutFailed(BaseModel):
    """``git checkout`` failed — usually dirty tree or invalid ref."""

    kind: Literal["git_checkout_failed"] = "git_checkout_failed"
    stderr: str

    def as_comment(self) -> str:
        return f"git checkout failed: {self.stderr}"


class NoStatusBlock(BaseModel):
    """Agent produced output without a parseable ``a2sdlc`` status block."""

    kind: Literal["no_status_block"] = "no_status_block"

    def as_comment(self) -> str:
        return "no status block in output"


class AgentFailed(BaseModel):
    """Agent run terminated with an error (runner-level failure)."""

    kind: Literal["agent_failed"] = "agent_failed"
    error: str

    def as_comment(self) -> str:
        return self.error or "unknown"


class StateSchemaTooNew(BaseModel):
    """Persisted TicketState schema is ahead of this engine (ADR-0005)."""

    kind: Literal["state_schema_too_new"] = "state_schema_too_new"
    found: int
    supported: int

    def as_comment(self) -> str:
        return (
            f"TicketState schema_version {self.found} is newer than supported "
            f"version {self.supported} — upgrade the engine"
        )


class Generic(BaseModel):
    """Escape hatch for reasons not yet structured. Each Generic usage is an
    invitation to promote a new variant.
    """

    kind: Literal["generic"] = "generic"
    message: str

    def as_comment(self) -> str:
        return self.message


BlockReason = Annotated[
    ReviewCyclesExceeded
    | CostCeilingExceeded
    | MergeConflict
    | GitCheckoutFailed
    | NoStatusBlock
    | AgentFailed
    | StateSchemaTooNew
    | Generic,
    Field(discriminator="kind"),
]


__all__ = [
    "AgentFailed",
    "BlockReason",
    "CostCeilingExceeded",
    "Generic",
    "GitCheckoutFailed",
    "MergeConflict",
    "NoStatusBlock",
    "ReviewCyclesExceeded",
    "StateSchemaTooNew",
]
