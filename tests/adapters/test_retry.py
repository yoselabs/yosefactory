"""Tests for must_succeed retry wrapper."""

from __future__ import annotations

import logging

import pytest

from a2sdlc.adapters.retry import must_succeed
from a2sdlc.domain.exceptions import AuthError, TransientError


@pytest.mark.unit
class TestMustSucceed:
    def test_succeeds_on_first_try(self) -> None:
        """Function called once; correct return value is returned."""
        calls = []

        def fn() -> str:
            calls.append(1)
            return "ok"

        result = must_succeed(fn, wait_multiplier=0.01, wait_max=0.01)
        assert result == "ok"
        assert len(calls) == 1

    def test_retries_on_transient_error_succeeds_on_third(self) -> None:
        """Function is retried; succeeds on 3rd attempt."""
        calls = []

        def fn() -> str:
            calls.append(1)
            if len(calls) < 3:
                raise TransientError("flaky")
            return "done"

        result = must_succeed(fn, wait_multiplier=0.01, wait_max=0.01)
        assert result == "done"
        assert len(calls) == 3

    def test_raises_immediately_on_auth_error(self) -> None:
        """PermanentError is not retried — function called once."""
        calls = []

        def fn() -> None:
            calls.append(1)
            raise AuthError("token expired")

        with pytest.raises(AuthError):
            must_succeed(fn, wait_multiplier=0.01, wait_max=0.01)

        assert len(calls) == 1

    def test_raises_after_max_attempts_exhausted(self) -> None:
        """After max_attempts retries all raise TransientError, re-raises last."""
        calls = []

        def fn() -> None:
            calls.append(1)
            raise TransientError("always fails")

        with pytest.raises(TransientError):
            must_succeed(fn, max_attempts=2, wait_multiplier=0.01, wait_max=0.01)

        assert len(calls) == 2

    def test_each_retry_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Each retry (not the first call) produces a WARNING log record."""
        calls = []

        def fn() -> str:
            calls.append(1)
            if len(calls) < 3:
                raise TransientError("retry me")
            return "ok"

        with caplog.at_level(logging.WARNING, logger="a2sdlc.adapters.retry"):
            must_succeed(fn, wait_multiplier=0.01, wait_max=0.01)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        # 2 retries → 2 warning log records
        assert len(warnings) == 2

    def test_non_retryable_non_permanent_exception_raises_immediately(self) -> None:
        """Arbitrary exceptions are not retried — raised immediately."""
        calls = []

        def fn() -> None:
            calls.append(1)
            raise ValueError("unexpected")

        with pytest.raises(ValueError, match="unexpected"):
            must_succeed(fn, wait_multiplier=0.01, wait_max=0.01)

        assert len(calls) == 1
