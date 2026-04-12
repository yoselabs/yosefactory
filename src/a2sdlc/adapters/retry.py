"""Retry wrapper for must-succeed adapter calls.

Usage::

    from a2sdlc.adapters.retry import must_succeed
    from a2sdlc.exceptions import RetryableError

    result = must_succeed(some_adapter_fn, arg1, arg2, kwarg=value)

must_succeed retries on RetryableError with exponential back-off and re-raises
immediately on PermanentError or any other exception type.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from a2sdlc.exceptions import PermanentError, RetryableError

logger = logging.getLogger("a2sdlc.adapters.retry")

T = TypeVar("T")

_DEFAULT_MAX_ATTEMPTS = 5
_DEFAULT_WAIT_MULTIPLIER = 1.0
_DEFAULT_WAIT_MAX = 60.0


def _make_log_before_sleep(fn_name: str) -> Callable[[RetryCallState], None]:
    """Return a before_sleep callback that logs a structured WARNING."""

    def _log(retry_state: RetryCallState) -> None:
        attempt = retry_state.attempt_number
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        logger.warning(
            "Retrying %s (attempt %d): %s: %s",
            fn_name,
            attempt,
            type(exc).__name__ if exc else "unknown",
            exc,
            extra={
                "fn": fn_name,
                "attempt": attempt,
                "exc_type": type(exc).__name__ if exc else None,
            },
        )

    return _log


def must_succeed(
    fn: Callable[..., T],
    *args: Any,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    wait_multiplier: float = _DEFAULT_WAIT_MULTIPLIER,
    wait_max: float = _DEFAULT_WAIT_MAX,
    **kwargs: Any,
) -> T:
    """Call *fn* with *args*/*kwargs*, retrying on RetryableError.

    Parameters
    ----------
    fn:
        The callable to invoke.
    *args:
        Positional arguments forwarded to *fn*.
    max_attempts:
        Maximum total attempts (first call + retries).  Default 5.
    wait_multiplier:
        Exponential back-off multiplier in seconds.  Set to a tiny value in
        tests to keep them fast (e.g. ``wait_multiplier=0.01``).
    wait_max:
        Cap on back-off wait time in seconds.
    **kwargs:
        Keyword arguments forwarded to *fn*.  The special keys
        ``max_attempts``, ``wait_multiplier``, and ``wait_max`` are consumed
        by this wrapper and are NOT passed through to *fn*.

    Raises
    ------
    RetryableError
        Re-raised when all *max_attempts* are exhausted.
    PermanentError
        Re-raised immediately on first occurrence — no retry.
    Exception
        Any other exception type is also re-raised immediately.
    """

    @retry(
        retry=retry_if_exception_type(RetryableError),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=wait_multiplier, max=wait_max),
        before_sleep=_make_log_before_sleep(getattr(fn, "__name__", repr(fn))),
        reraise=True,
    )
    def _inner() -> T:
        try:
            return fn(*args, **kwargs)
        except PermanentError:
            # Wrap in a non-retryable sentinel so tenacity doesn't catch it.
            # We re-raise directly; tenacity only retries RetryableError.
            raise
        except RetryableError:
            raise

    return _inner()
