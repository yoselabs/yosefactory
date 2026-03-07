"""Adapter registry."""

from __future__ import annotations

from a2sdlc.adapters.protocols import (
    DispatchInput,
    GitAdapter,
    StageRunner,
    TicketAdapter,
)

__all__ = ["DispatchInput", "GitAdapter", "StageRunner", "TicketAdapter"]
