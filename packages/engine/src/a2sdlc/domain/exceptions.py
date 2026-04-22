"""Pipeline exceptions — typed errors with reasons."""

from __future__ import annotations


class SkipEvent(Exception):
    """Event is not actionable — log and exit cleanly."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class AdapterError(Exception):
    """Base class for all adapter errors."""


class RetryableError(AdapterError):
    """Error that can be retried."""


class PermanentError(AdapterError):
    """Error that cannot be retried — propagate immediately."""


class BlockedError(PermanentError):
    """Unrecoverable error — set stage:blocked label and exit."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class StateSchemaTooNew(PermanentError):
    """Reader encountered a TicketState with schema_version greater than it supports.

    Per ADR-0005, backward compatibility is not guaranteed — a v2 reader may
    not read a v3 document. This is a permanent error (not retryable); the
    engine must be upgraded before the state can be read.
    """

    def __init__(self, found: int, supported: int) -> None:
        self.found = found
        self.supported = supported
        super().__init__(
            f"TicketState schema_version {found} is newer than supported version "
            f"{supported} — upgrade the engine",
        )


class StateSchemaRegression(PermanentError):
    """Attempted to write a TicketState with an older schema_version than persisted.

    Per ADR-0005 invariant I7, schema_version monotonically increases within
    a ticket's lifetime. Catches deployment mistakes (older engine writing
    over newer state).
    """

    def __init__(self, existing: int, attempted: int) -> None:
        self.existing = existing
        self.attempted = attempted
        super().__init__(
            f"cannot downgrade TicketState schema_version from {existing} to "
            f"{attempted}",
        )
