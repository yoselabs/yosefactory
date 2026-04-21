"""Telemetry abstraction — context manager + null object over MLflow.

SSOT for ``MLFLOW_TRACKING_URI`` env reading. No other module in a2sdlc
should call ``os.environ`` for MLflow configuration. Callers use the
``Telemetry`` protocol; the null object (``NoopTelemetry``) absorbs all
calls when tracking is disabled so call sites stay branch-free.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Protocol, runtime_checkable


class MlflowUnreachableError(RuntimeError):
    """Raised when the MLflow backend is not reachable."""


@runtime_checkable
class RunHandle(Protocol):
    def log_metric(self, key: str, value: float) -> None: ...
    def log_tag(self, key: str, value: str) -> None: ...
    def log_dict(self, data: dict[str, object], artifact_path: str) -> None: ...
    def log_artifact(self, local_path: str) -> None: ...


@runtime_checkable
class StageOpener(Protocol):
    def stage(self, name: str) -> Iterator[RunHandle]: ...


@runtime_checkable
class Telemetry(Protocol):
    def session(self, session_id: str) -> Iterator[StageOpener]: ...

    @property
    def traces_enabled(self) -> bool: ...


# ── Null object ────────────────────────────────────────────────────────


class _NoopRun:
    def log_metric(self, key: str, value: float) -> None:  # noqa: ARG002
        return None

    def log_tag(self, key: str, value: str) -> None:  # noqa: ARG002
        return None

    def log_dict(self, data: dict[str, object], artifact_path: str) -> None:  # noqa: ARG002
        return None

    def log_artifact(self, local_path: str) -> None:  # noqa: ARG002
        return None


class _NoopOpener:
    @contextlib.contextmanager
    def stage(self, name: str) -> Iterator[_NoopRun]:  # noqa: ARG002
        yield _NoopRun()


class NoopTelemetry:
    """Null-object telemetry — every call is a no-op.

    Used when ``MLFLOW_TRACKING_URI`` is unset, or explicitly by local
    ``run_stage --no-track``.
    """

    @contextlib.contextmanager
    def session(self, session_id: str) -> Iterator[_NoopOpener]:  # noqa: ARG002
        yield _NoopOpener()

    @property
    def traces_enabled(self) -> bool:
        return False
