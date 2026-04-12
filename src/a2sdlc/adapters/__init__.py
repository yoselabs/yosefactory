"""Adapter registry."""

from __future__ import annotations

from a2sdlc.adapters.protocols import (
    DispatchInput,
    GitAdapter,
    StageRunner,
    TicketAdapter,
)
from a2sdlc.adapters.review import Approval, ReviewAdapter, ReviewComment
from a2sdlc.adapters.work import PipelineEvent, WorkAdapter

__all__ = [
    # Legacy — kept for backward compat until Task 16
    "DispatchInput",
    "TicketAdapter",
    # Stable
    "GitAdapter",
    "StageRunner",
    # New
    "PipelineEvent",
    "WorkAdapter",
    "Approval",
    "ReviewComment",
    "ReviewAdapter",
]
