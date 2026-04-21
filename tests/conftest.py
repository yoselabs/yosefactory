"""Root pytest fixtures for a2sdlc tests."""

from __future__ import annotations

from collections.abc import Callable, Iterator
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


@pytest.fixture(autouse=True)
def _reset_mlflow_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Isolate MLflow process-global state between tests.

    Two vectors get reset before and after each test:

    1. **Active-run stack.** MLflow keeps it on module-level globals.
       Under pytest-xdist each worker is its own process, but within a
       worker tests run serially and can still pollute each other if
       one leaves a run open.
    2. **``MLFLOW_TRACKING_URI`` env var.** ``mlflow.set_tracking_uri``
       side-effects ``os.environ`` — a test that sets a URI via the
       mlflow API leaks it to downstream tests that read env (e.g.
       ``local_fallback_telemetry`` in ``a2sdlc.evaluation.telemetry``).

    Tests that need a specific URI call ``monkeypatch.setenv`` in their
    own body; that runs AFTER this autouse fixture, so the explicit
    setenv wins.
    """
    import mlflow  # noqa: PLC0415

    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    while mlflow.active_run() is not None:
        mlflow.end_run(status="KILLED")

    yield

    while mlflow.active_run() is not None:
        mlflow.end_run(status="KILLED")
