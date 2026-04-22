"""Event sum type — the V1.0 event ADT.

Architecture vision §7.2 three-load-bearing types. Replaces the
``PipelineEvent`` flag-bag (``is_closed``/``is_feedback``/
``trigger_stage``/``pr_number``) with a discriminated union so routing
becomes a ``match`` statement and type-system exhaustiveness catches
missing arms.

P1 lands the types and the ``pipeline_event_to_event`` bridge helper.
No call-site adoption — ``pipeline/dispatch.py`` still routes on
``PipelineEvent``. P4 will swap routing to the Event ADT.

Naming note: the ADT's "skip" variant is ``SkipSignal``, not
``SkipEvent``, because ``SkipEvent`` is already an Exception in
``domain/exceptions.py`` with 15+ call sites. Renaming the exception
is P4 territory — keep names unambiguous in the meantime.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from a2sdlc.domain.models import StageName


class FeedbackSource(StrEnum):
    """Where a feedback event originated."""

    ISSUE_COMMENT = "issue_comment"
    PR_REVIEW = "pr_review"
    PR_INLINE_COMMENT = "pr_inline_comment"


class TicketClosedEvent(BaseModel):
    """Ticket closed by human or tracker. Engine strips stage labels, no AI runs."""

    kind: Literal["ticket_closed"] = "ticket_closed"
    key: str


class LabelTriggerEvent(BaseModel):
    """A stage label was set — run that stage next.

    ``pr_number`` is None for issue-side labels (SPEC/IMPLEMENT) and set
    for PR-side labels (REVIEW/MERGE).
    """

    kind: Literal["label_trigger"] = "label_trigger"
    key: str
    stage: StageName
    pr_number: int | None = None


class FeedbackEvent(BaseModel):
    """Comment / PR review / inline comment — route via current stage."""

    kind: Literal["feedback"] = "feedback"
    key: str
    source: FeedbackSource
    pr_number: int | None = None


class ProceedEvent(BaseModel):
    """Stage finished upstream — continue in the same run."""

    kind: Literal["proceed"] = "proceed"
    key: str
    current_stage: StageName | None = None


class SkipSignal(BaseModel):
    """Non-actionable event — log reason and exit cleanly.

    Named ``SkipSignal`` to avoid collision with ``domain.exceptions.SkipEvent``
    (an Exception raised by adapters during parse). P4 will collapse the
    two once ingress routes exclusively through this ADT.
    """

    kind: Literal["skip"] = "skip"
    reason: str


Event = Annotated[
    TicketClosedEvent | LabelTriggerEvent | FeedbackEvent | ProceedEvent | SkipSignal,
    Field(discriminator="kind"),
]


# ── Bridge: PipelineEvent -> Event ────────────────────────────────────
# Step 8. Helper for P4's pipe-and-filter dispatch to adopt the ADT
# without touching the adapter layer. ``PipelineEvent`` stays as the
# wire shape from adapters until P4; this function converts at the
# pipeline boundary.


def pipeline_event_to_event(pe: "PipelineEvent") -> Event:
    """Translate the legacy flag-bag ``PipelineEvent`` to the Event ADT.

    Mapping rules reflect today's dispatch triangulation:
    - ``is_closed``        → ``TicketClosedEvent``
    - ``trigger_stage``    → ``LabelTriggerEvent`` (stage + optional pr_number)
    - ``is_feedback``      → ``FeedbackEvent`` (source inferred from pr_number)
    - otherwise            → ``ProceedEvent`` (current_stage resolved upstream)
    """
    from a2sdlc.domain.pipeline_event import PipelineEvent as _PE  # noqa: F401

    if pe.is_closed:
        return TicketClosedEvent(key=pe.key)
    if pe.trigger_stage is not None:
        return LabelTriggerEvent(
            key=pe.key,
            stage=pe.trigger_stage,
            pr_number=pe.pr_number,
        )
    if pe.is_feedback:
        source = (
            FeedbackSource.PR_REVIEW
            if pe.pr_number is not None
            else FeedbackSource.ISSUE_COMMENT
        )
        return FeedbackEvent(
            key=pe.key,
            source=source,
            pr_number=pe.pr_number,
        )
    return ProceedEvent(key=pe.key)


# Typing import kept behind TYPE_CHECKING to avoid cycles at runtime.
from typing import TYPE_CHECKING  # noqa: E402

if TYPE_CHECKING:
    from a2sdlc.domain.pipeline_event import PipelineEvent


__all__ = [
    "Event",
    "FeedbackEvent",
    "FeedbackSource",
    "LabelTriggerEvent",
    "ProceedEvent",
    "SkipSignal",
    "TicketClosedEvent",
    "pipeline_event_to_event",
]
