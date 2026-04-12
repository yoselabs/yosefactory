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


class RateLimitError(RetryableError):
    """Rate limit hit — retry after a delay."""

    def __init__(self, message: str, retry_after: float = 0.0) -> None:
        self.retry_after = retry_after
        super().__init__(message)


class TransientError(RetryableError):
    """Transient adapter failure — safe to retry."""


class AuthError(PermanentError):
    """Authentication or authorisation failure."""


class NotFoundError(PermanentError):
    """Requested resource does not exist."""


class PlatformValidationError(PermanentError):
    """Platform rejected the request due to invalid input."""


class BlockedError(PermanentError):
    """Unrecoverable error — set stage:blocked label and exit."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)
