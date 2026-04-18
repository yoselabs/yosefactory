"""MLflow telemetry sink — parent run per session, child run per stage invocation.

Thin wrapper over the ``mlflow`` Python API. One parent run per *session*
(``session:<sid>``) with nested child runs per *stage* invocation
(``<sid>:<stage>``). Metrics and tags logged through the yielded
``_StageRun`` land on the active child run.

The module is imported lazily from ``cli_local`` so the ``--no-track``
path does not pay the mlflow import cost.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import dataclass

import mlflow


class MlflowUnreachableError(RuntimeError):
    """Raised when the MLflow backend is not reachable."""


@dataclass
class _StageRun:
    """Handle to an active MLflow child run — exposes metric/tag logging."""

    run_id: str

    def log_metric(self, key: str, value: float) -> None:
        mlflow.log_metric(key, value, run_id=self.run_id)

    def log_tag(self, key: str, value: str) -> None:
        mlflow.set_tag(key, value)


@dataclass
class _SessionRun:
    """Handle to an active MLflow parent run — spawns child stage runs."""

    parent_run_id: str
    session_id: str

    @contextlib.contextmanager
    def stage_run(self, stage: str) -> Iterator[_StageRun]:
        """Open a nested child run for *stage* under the current session."""
        with mlflow.start_run(nested=True, run_name=f"{self.session_id}:{stage}") as r:
            mlflow.set_tag("stage", stage)
            mlflow.set_tag("session_id", self.session_id)
            yield _StageRun(run_id=r.info.run_id)


class MlflowSink:
    """Per-session/per-stage MLflow tracking sink."""

    def __init__(self, tracking_uri: str, experiment_name: str) -> None:
        self._uri = tracking_uri
        self._experiment = experiment_name
        mlflow.set_tracking_uri(tracking_uri)

    def verify_reachable(self, timeout_s: float = 5.0) -> None:
        """Force a backend interaction; raise ``MlflowUnreachableError`` on failure."""
        try:
            mlflow.set_experiment(self._experiment)
        except Exception as e:  # noqa: BLE001
            raise MlflowUnreachableError(str(e)) from e

    @contextlib.contextmanager
    def session(self, session_id: str) -> Iterator[_SessionRun]:
        """Open a parent run for *session_id*; yield a ``_SessionRun`` handle."""
        mlflow.set_experiment(self._experiment)
        with mlflow.start_run(run_name=f"session:{session_id}") as parent:
            yield _SessionRun(parent_run_id=parent.info.run_id, session_id=session_id)
