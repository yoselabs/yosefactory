"""Tests for a2sdlc exception hierarchy."""

from __future__ import annotations

import pytest

from a2sdlc.domain.exceptions import (
    AdapterError,
    AuthError,
    BlockedError,
    NotFoundError,
    PermanentError,
    PlatformValidationError,
    RateLimitError,
    RetryableError,
    SkipEvent,
    TransientError,
)


@pytest.mark.unit
class TestSkipEvent:
    def test_stores_reason(self) -> None:
        exc = SkipEvent("label 'bug' is not a stage label")
        assert exc.reason == "label 'bug' is not a stage label"
        assert "bug" in str(exc)

    def test_is_exception(self) -> None:
        with pytest.raises(SkipEvent):
            raise SkipEvent("test")

    def test_is_not_adapter_error(self) -> None:
        assert not issubclass(SkipEvent, AdapterError)


@pytest.mark.unit
class TestHierarchy:
    def test_adapter_error_is_exception(self) -> None:
        assert issubclass(AdapterError, Exception)

    def test_retryable_error_is_adapter_error(self) -> None:
        assert issubclass(RetryableError, AdapterError)

    def test_permanent_error_is_adapter_error(self) -> None:
        assert issubclass(PermanentError, AdapterError)

    def test_rate_limit_error_is_retryable(self) -> None:
        assert issubclass(RateLimitError, RetryableError)

    def test_transient_error_is_retryable(self) -> None:
        assert issubclass(TransientError, RetryableError)

    def test_auth_error_is_permanent(self) -> None:
        assert issubclass(AuthError, PermanentError)

    def test_not_found_error_is_permanent(self) -> None:
        assert issubclass(NotFoundError, PermanentError)

    def test_platform_validation_error_is_permanent(self) -> None:
        assert issubclass(PlatformValidationError, PermanentError)

    def test_blocked_error_is_permanent(self) -> None:
        assert issubclass(BlockedError, PermanentError)


@pytest.mark.unit
class TestRateLimitError:
    def test_default_retry_after(self) -> None:
        exc = RateLimitError("rate limit hit")
        assert exc.retry_after == 0.0

    def test_custom_retry_after(self) -> None:
        exc = RateLimitError("rate limit hit", retry_after=30.5)
        assert exc.retry_after == 30.5

    def test_is_raisable(self) -> None:
        with pytest.raises(RateLimitError):
            raise RateLimitError("rate limit hit")

    def test_caught_as_retryable(self) -> None:
        with pytest.raises(RetryableError):
            raise RateLimitError("rate limit hit")

    def test_caught_as_adapter_error(self) -> None:
        with pytest.raises(AdapterError):
            raise RateLimitError("rate limit hit")


@pytest.mark.unit
class TestBlockedError:
    def test_stores_reason(self) -> None:
        exc = BlockedError("merge conflict with main")
        assert exc.reason == "merge conflict with main"
        assert "conflict" in str(exc)

    def test_is_permanent(self) -> None:
        assert issubclass(BlockedError, PermanentError)

    def test_caught_as_permanent(self) -> None:
        with pytest.raises(PermanentError):
            raise BlockedError("conflict")

    def test_caught_as_adapter_error(self) -> None:
        with pytest.raises(AdapterError):
            raise BlockedError("conflict")
