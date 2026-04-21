"""Telemetry abstraction — context manager + null object over MLflow.

SSOT for ``MLFLOW_TRACKING_URI`` env reading. No other module in a2sdlc
should call ``os.environ`` for MLflow configuration. Callers use the
``Telemetry`` protocol; the null object (``NoopTelemetry``) absorbs all
calls when tracking is disabled so call sites stay branch-free.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast, runtime_checkable


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
    def stage(self, name: str) -> AbstractContextManager[RunHandle]: ...


@runtime_checkable
class Telemetry(Protocol):
    def session(self, session_id: str) -> AbstractContextManager[StageOpener]: ...

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


# ── MLflow implementation ─────────────────────────────────────────────


@dataclass
class _MlflowRun:
    run_id: str

    def log_metric(self, key: str, value: float) -> None:
        import mlflow  # noqa: PLC0415

        mlflow.log_metric(key, value, run_id=self.run_id)

    def log_tag(self, key: str, value: str) -> None:
        import mlflow  # noqa: PLC0415

        mlflow.MlflowClient().set_tag(self.run_id, key, value)

    def log_dict(self, data: dict[str, object], artifact_path: str) -> None:
        import mlflow  # noqa: PLC0415

        mlflow.log_dict(data, artifact_path)

    def log_artifact(self, local_path: str) -> None:
        import mlflow  # noqa: PLC0415

        mlflow.log_artifact(local_path)


@dataclass
class _MlflowOpener:
    session_id: str

    @contextlib.contextmanager
    def stage(self, name: str) -> Iterator[_MlflowRun]:
        import mlflow  # noqa: PLC0415

        with mlflow.start_run(nested=True, run_name=f"{self.session_id}:{name}") as r:
            mlflow.set_tag("stage", name)
            mlflow.set_tag("session_id", self.session_id)
            yield _MlflowRun(run_id=r.info.run_id)


class MlflowTelemetry:
    """Real MLflow-backed telemetry. Parent run per session, nested child run per stage."""

    def __init__(self, tracking_uri: str, experiment_name: str) -> None:
        import mlflow  # noqa: PLC0415

        self._uri = tracking_uri
        self._experiment = experiment_name
        mlflow.set_tracking_uri(tracking_uri)

    def verify_reachable(self) -> None:
        import mlflow  # noqa: PLC0415

        try:
            mlflow.set_experiment(self._experiment)
        except Exception as e:  # noqa: BLE001
            raise MlflowUnreachableError(str(e)) from e

    @contextlib.contextmanager
    def session(self, session_id: str) -> Iterator[_MlflowOpener]:
        import mlflow  # noqa: PLC0415

        mlflow.set_experiment(self._experiment)
        run_name = f"session:{session_id}"
        existing = mlflow.search_runs(
            experiment_names=[self._experiment],
            filter_string=f"tags.mlflow.runName = '{run_name}'",
            output_format="list",
            max_results=1,
            order_by=["attributes.start_time DESC"],
        )
        existing_run_id: str | None = existing[0].info.run_id if existing else None
        if existing_run_id is not None:
            cm = mlflow.start_run(run_id=existing_run_id)
        else:
            cm = mlflow.start_run(run_name=run_name)
        with cm:
            yield _MlflowOpener(session_id=session_id)

    @property
    def traces_enabled(self) -> bool:
        return True


# ── Factory (SSOT for MLFLOW_TRACKING_URI) ────────────────────────────


def telemetry_from_env(experiment_name: str) -> Telemetry:
    """Return an MLflow-backed telemetry if env is configured, else a null.

    This is the **only** place in a2sdlc that reads ``MLFLOW_TRACKING_URI``.
    """
    uri = os.environ.get("MLFLOW_TRACKING_URI")
    if not uri:
        # cast: ty doesn't infer structural Protocol conformance for concrete classes
        return cast(Telemetry, NoopTelemetry())
    m = MlflowTelemetry(tracking_uri=uri, experiment_name=experiment_name)
    m.verify_reachable()
    # cast: ty doesn't infer structural Protocol conformance for concrete classes
    return cast(Telemetry, m)


def local_fallback_telemetry(experiment_name: str) -> Telemetry:
    """For ``a2sdlc run-stage`` local dev UX: env URI if set, else ~/.a2sdlc/mlflow.

    Never returns ``NoopTelemetry`` — local dev expects *some* MLflow store by
    default. Use ``NoopTelemetry()`` directly for ``--no-track``.
    """
    uri = (
        os.environ.get("MLFLOW_TRACKING_URI")
        or f"file://{Path.home() / '.a2sdlc' / 'mlflow'}"
    )
    m = MlflowTelemetry(tracking_uri=uri, experiment_name=experiment_name)
    m.verify_reachable()
    # cast: ty doesn't infer structural Protocol conformance for concrete classes
    return cast(Telemetry, m)
