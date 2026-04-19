"""Root pytest fixtures for a2sdlc tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from tests.fakes import make_dispatch_context


@pytest.fixture
def dispatch_context_factory() -> Callable[..., Any]:
    """Factory fixture returning ``make_dispatch_context``.

    Tests override per-case kwargs:

        def test_something(dispatch_context_factory):
            ctx, work, git, review, runner = dispatch_context_factory(
                event=..., runner_results=[...],
            )
    """
    return make_dispatch_context
