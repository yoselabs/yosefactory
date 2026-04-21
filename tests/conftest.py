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
def _reset_mlflow_active_runs() -> Iterator[None]:
    """Close any MLflow run left open by the previous test.

    MLflow keeps the active-run stack on module-level globals. Under
    pytest-xdist each worker is its own process, but within a worker
    tests run serially and can still pollute each other if one leaves
    a run open. This fixture closes any stray run before and after each
    test. Cheap — just an ``active_run()`` pointer check when no run is
    open (the common case).

    Tracking URI is NOT reset here because every ``MlflowTelemetry``
    constructor calls ``mlflow.set_tracking_uri`` on its own, so URI
    leaks are self-corrected. Tests that need a specific URI should
    set ``MLFLOW_TRACKING_URI`` via ``monkeypatch.setenv`` or construct
    the telemetry directly with the desired URI.
    """
    import mlflow  # noqa: PLC0415

    while mlflow.active_run() is not None:
        mlflow.end_run(status="KILLED")

    yield

    while mlflow.active_run() is not None:
        mlflow.end_run(status="KILLED")
