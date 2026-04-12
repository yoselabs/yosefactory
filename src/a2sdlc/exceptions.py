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


# ---------------------------------------------------------------------------
# Adapter error taxonomy
# ---------------------------------------------------------------------------


class AdapterError(Exception):
    """Base class for all adapter errors."""


class RetryableError(AdapterError):
    """Adapter call failed but may succeed on retry."""


class TransientError(RetryableError):
    """Network timeout, 502/503, or other transient infrastructure failure."""


class RateLimitError(RetryableError):
    """API rate-limit hit; caller may inspect retry_after to back off."""

    def __init__(self, message: str = "", retry_after: float = 0.0) -> None:
        self.retry_after = retry_after
        super().__init__(message)


class PermanentError(AdapterError):
    """Adapter call failed with a non-recoverable error — do NOT retry."""


class AuthError(PermanentError):
    """Token expired or credential rejected."""
