"""Pipeline exceptions — typed errors with reasons."""

from __future__ import annotations


class SkipEvent(Exception):
    """Event is not actionable — log and exit cleanly."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class BlockedError(Exception):
    """Unrecoverable error — set stage:blocked label and exit."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)
