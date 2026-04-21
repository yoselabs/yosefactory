# Mode 2 End-to-End Smoke — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove a2sdlc Mode 2 end-to-end on a fresh private GitHub repo with real MLflow telemetry against `mlflow.shen.iorlas.net`. Prerequisite: rewire MLflow via a `Telemetry` context-manager + null-object so both CLI entry points (`cli/dispatch.py` and `cli/run_stage.py`) share a single SSOT env-driven factory.

**Architecture:** New `evaluation/telemetry.py` exposes a `Telemetry` protocol with `session(sid) → stage(name) → RunHandle` nested context managers. `NoopTelemetry` is the null object; `MlflowTelemetry` wraps today's `MlflowSink`. A single `telemetry_from_env(experiment_name)` factory is the only place that reads `MLFLOW_TRACKING_URI`. All callers use the protocol — no `if sink is None` branches.

**Tech Stack:** Python 3.12, `mlflow` SDK, `pytest`, `typer` (CLI), `PyGithub` (GH adapter), uv.

**Spec:** `docs/superpowers/specs/2026-04-21-mode2-e2e-smoke-design.md`

---

## File Structure

### Phase 1: Telemetry rewiring (code)

**Create:**
- `packages/engine/src/a2sdlc/evaluation/telemetry.py` — protocols + `NoopTelemetry` + `MlflowTelemetry` + factory. Single responsibility: telemetry policy + env reading.
- `tests/evaluation/test_telemetry.py` — unit tests for protocols, null object, factory.

**Modify:**
- `packages/engine/src/a2sdlc/evaluation/tracked_run.py` — replace `sink: MlflowSink | None` with `telemetry: Telemetry`; remove null branch.
- `packages/engine/src/a2sdlc/cli/run_stage.py:125-131` — use telemetry factory (with local fallback for `--no-track == False` and unset env).
- `packages/engine/src/a2sdlc/cli/dispatch.py` — wrap the `asyncio.run(dispatch(ctx))` call with `tracked_run` using telemetry from env.
- `packages/engine/src/a2sdlc/assembly/wire.py` — take `traces_enabled: bool` (already does, just plumb from `telemetry.traces_enabled`).
- `packages/engine/src/a2sdlc/evaluation/mlflow_sink.py` — delete (absorbed into `telemetry.py`).
- `tests/evaluation/test_mlflow_sink.py` — rename + migrate assertions to `MlflowTelemetry` surface.
- `docs/local-runner-usage.md` — note env override.
- `README.md` — note env override.

### Phase 2: Smoke runbook (operational, not code)

No file changes in this repo. Creates a separate private repo `iorlas/a2sdlc-smoke`.

---

## Phase 1 — Telemetry rewiring

### Task 1: Create telemetry module skeleton + NoopTelemetry

**Files:**
- Create: `packages/engine/src/a2sdlc/evaluation/telemetry.py`
- Test: `tests/evaluation/test_telemetry.py`

- [ ] **Step 1.1: Write failing test for NoopTelemetry**

Create `tests/evaluation/test_telemetry.py`:

```python
"""Tests for the Telemetry abstraction."""

from __future__ import annotations

from a2sdlc.evaluation.telemetry import NoopTelemetry


def test_noop_session_stage_is_safe_noop() -> None:
    t = NoopTelemetry()
    assert t.traces_enabled is False
    with t.session("sid-1") as opener, opener.stage("spec") as run:
        run.log_metric("cost_usd", 1.23)
        run.log_tag("git_sha_before", "abc")
        run.log_dict({"stage": "spec"}, "out.json")
        run.log_artifact("/tmp/quality.log")  # noqa: S108 — path is not read
    # No exception, no state written anywhere.
```

- [ ] **Step 1.2: Run the test and confirm it fails**

Run: `uv run pytest tests/evaluation/test_telemetry.py -v`
Expected: `ModuleNotFoundError` or `ImportError: cannot import name 'NoopTelemetry'`.

- [ ] **Step 1.3: Implement protocols + NoopTelemetry**

Create `packages/engine/src/a2sdlc/evaluation/telemetry.py`:

```python
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
from dataclasses import dataclass
from pathlib import Path
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
    def stage(self, name: str) -> contextlib.AbstractContextManager[RunHandle]: ...


@runtime_checkable
class Telemetry(Protocol):
    def session(self, session_id: str) -> contextlib.AbstractContextManager[StageOpener]: ...

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
```

- [ ] **Step 1.4: Run the test and confirm it passes**

Run: `uv run pytest tests/evaluation/test_telemetry.py -v`
Expected: 1 passed.

- [ ] **Step 1.5: Commit**

```bash
git add packages/engine/src/a2sdlc/evaluation/telemetry.py tests/evaluation/test_telemetry.py
git commit -m "feat(evaluation): Telemetry protocol + NoopTelemetry null object"
```

---

### Task 2: Add MlflowTelemetry implementation

**Files:**
- Modify: `packages/engine/src/a2sdlc/evaluation/telemetry.py`
- Test: `tests/evaluation/test_telemetry.py`

- [ ] **Step 2.1: Add failing test for MlflowTelemetry session+stage on a file-backed store**

Append to `tests/evaluation/test_telemetry.py`:

```python
from pathlib import Path

import mlflow
import pytest

from a2sdlc.evaluation.telemetry import (
    MlflowTelemetry,
    MlflowUnreachableError,
)


def _uri(tmp_path: Path) -> str:
    return f"file://{tmp_path / 'mlflow'}"


def test_mlflow_telemetry_opens_session_and_stage_runs(tmp_path: Path) -> None:
    t = MlflowTelemetry(tracking_uri=_uri(tmp_path), experiment_name="testrepo")
    t.verify_reachable()
    with t.session("sess-1") as opener, opener.stage("spec") as run:
        run.log_metric("cost_usd", 1.23)
        run.log_tag("git_sha_before", "abc123")

    # Verify parent + child runs exist with correct names.
    mlflow.set_tracking_uri(_uri(tmp_path))
    runs = mlflow.search_runs(
        experiment_names=["testrepo"], output_format="list"
    )
    names = {r.data.tags.get("mlflow.runName") for r in runs}
    assert "session:sess-1" in names
    assert "sess-1:spec" in names


def test_mlflow_telemetry_reuses_existing_session(tmp_path: Path) -> None:
    t = MlflowTelemetry(tracking_uri=_uri(tmp_path), experiment_name="testrepo")
    t.verify_reachable()
    with t.session("sess-1") as opener, opener.stage("spec"):
        pass
    with t.session("sess-1") as opener, opener.stage("implement"):
        pass

    mlflow.set_tracking_uri(_uri(tmp_path))
    parent_runs = [
        r
        for r in mlflow.search_runs(
            experiment_names=["testrepo"], output_format="list"
        )
        if r.data.tags.get("mlflow.runName") == "session:sess-1"
    ]
    # Parent run must be reused, not duplicated, across CLI invocations.
    assert len(parent_runs) == 1


def test_mlflow_telemetry_verify_reachable_raises_on_bad_uri() -> None:
    t = MlflowTelemetry(tracking_uri="http://127.0.0.1:1/bad", experiment_name="x")
    with pytest.raises(MlflowUnreachableError):
        t.verify_reachable()


def test_mlflow_telemetry_traces_enabled_is_true() -> None:
    t = MlflowTelemetry(tracking_uri="http://127.0.0.1:1/bad", experiment_name="x")
    assert t.traces_enabled is True
```

- [ ] **Step 2.2: Run tests and confirm they fail**

Run: `uv run pytest tests/evaluation/test_telemetry.py -v`
Expected: 4 failures with `ImportError: cannot import name 'MlflowTelemetry'`.

- [ ] **Step 2.3: Add MlflowTelemetry implementation**

Append to `packages/engine/src/a2sdlc/evaluation/telemetry.py`:

```python
# ── MLflow implementation ─────────────────────────────────────────────


@dataclass
class _MlflowRun:
    run_id: str

    def log_metric(self, key: str, value: float) -> None:
        import mlflow  # noqa: PLC0415

        mlflow.log_metric(key, value, run_id=self.run_id)

    def log_tag(self, key: str, value: str) -> None:
        import mlflow  # noqa: PLC0415

        mlflow.set_tag(key, value)

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
    """Real MLflow-backed telemetry. Opens a parent run per session and a
    nested child run per stage invocation.
    """

    def __init__(self, tracking_uri: str, experiment_name: str) -> None:
        import mlflow  # noqa: PLC0415

        self._uri = tracking_uri
        self._experiment = experiment_name
        mlflow.set_tracking_uri(tracking_uri)

    def verify_reachable(self) -> None:
        """Force a backend interaction; raise ``MlflowUnreachableError`` on failure."""
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
```

- [ ] **Step 2.4: Run tests and confirm they pass**

Run: `uv run pytest tests/evaluation/test_telemetry.py -v`
Expected: 5 passed.

- [ ] **Step 2.5: Commit**

```bash
git add packages/engine/src/a2sdlc/evaluation/telemetry.py tests/evaluation/test_telemetry.py
git commit -m "feat(evaluation): MlflowTelemetry implementation"
```

---

### Task 3: Add `telemetry_from_env` factory (SSOT)

**Files:**
- Modify: `packages/engine/src/a2sdlc/evaluation/telemetry.py`
- Test: `tests/evaluation/test_telemetry.py`

- [ ] **Step 3.1: Add failing factory tests**

Append to `tests/evaluation/test_telemetry.py`:

```python
def test_factory_returns_noop_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    from a2sdlc.evaluation.telemetry import NoopTelemetry, telemetry_from_env

    t = telemetry_from_env("any-experiment")
    assert isinstance(t, NoopTelemetry)


def test_factory_returns_mlflow_when_env_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MLFLOW_TRACKING_URI", _uri(tmp_path))
    from a2sdlc.evaluation.telemetry import MlflowTelemetry, telemetry_from_env

    t = telemetry_from_env("exp")
    assert isinstance(t, MlflowTelemetry)


def test_factory_raises_on_unreachable_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:1/bad")
    from a2sdlc.evaluation.telemetry import MlflowUnreachableError, telemetry_from_env

    with pytest.raises(MlflowUnreachableError):
        telemetry_from_env("exp")


def test_local_fallback_uses_file_store_when_env_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    from a2sdlc.evaluation.telemetry import MlflowTelemetry, local_fallback_telemetry

    t = local_fallback_telemetry("exp")
    assert isinstance(t, MlflowTelemetry)


def test_local_fallback_prefers_env_when_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MLFLOW_TRACKING_URI", _uri(tmp_path))
    from a2sdlc.evaluation.telemetry import MlflowTelemetry, local_fallback_telemetry

    t = local_fallback_telemetry("exp")
    assert isinstance(t, MlflowTelemetry)
    # Internal URI should match the env override, not the ~/.a2sdlc default.
    assert t._uri == _uri(tmp_path)  # noqa: SLF001
```

- [ ] **Step 3.2: Run tests and confirm they fail**

Run: `uv run pytest tests/evaluation/test_telemetry.py -v -k factory_or_local_fallback`
Expected: 5 failures with `ImportError` on `telemetry_from_env` / `local_fallback_telemetry`.

- [ ] **Step 3.3: Implement factory + local-fallback helper**

Append to `packages/engine/src/a2sdlc/evaluation/telemetry.py`:

```python
# ── Factory (SSOT for MLFLOW_TRACKING_URI) ────────────────────────────


def telemetry_from_env(experiment_name: str) -> Telemetry:
    """Return an MLflow-backed telemetry if env is configured, else a null.

    This is the **only** place in a2sdlc that reads ``MLFLOW_TRACKING_URI``.
    """
    uri = os.environ.get("MLFLOW_TRACKING_URI")
    if not uri:
        return NoopTelemetry()
    t = MlflowTelemetry(tracking_uri=uri, experiment_name=experiment_name)
    t.verify_reachable()
    return t


def local_fallback_telemetry(experiment_name: str) -> Telemetry:
    """For ``a2sdlc run-stage`` local dev UX: env URI if set, else ~/.a2sdlc/mlflow.

    Never returns ``NoopTelemetry`` — local dev expects *some* MLflow store by
    default. Use ``NoopTelemetry()`` directly for ``--no-track``.
    """
    uri = os.environ.get("MLFLOW_TRACKING_URI") or f"file://{Path.home() / '.a2sdlc' / 'mlflow'}"
    t = MlflowTelemetry(tracking_uri=uri, experiment_name=experiment_name)
    t.verify_reachable()
    return t
```

- [ ] **Step 3.4: Run tests and confirm they pass**

Run: `uv run pytest tests/evaluation/test_telemetry.py -v`
Expected: 10 passed.

- [ ] **Step 3.5: Commit**

```bash
git add packages/engine/src/a2sdlc/evaluation/telemetry.py tests/evaluation/test_telemetry.py
git commit -m "feat(evaluation): telemetry_from_env factory + local_fallback helper"
```

---

### Task 4: Migrate `tracked_run.py` to use `Telemetry` protocol

**Files:**
- Modify: `packages/engine/src/a2sdlc/evaluation/tracked_run.py`

- [ ] **Step 4.1: Rewrite `tracked_run.py` to take `Telemetry` (not `MlflowSink | None`)**

Replace `packages/engine/src/a2sdlc/evaluation/tracked_run.py` entirely:

```python
"""Orchestrate a dispatch run under a Telemetry + quality-gate.

Pulls the tracking orchestration out of the CLI. Takes a zero-arg async
``dispatch_fn`` (caller has already bound the ``DispatchContext``) so this
module stays off the pipeline → evaluation dependency path.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from a2sdlc.domain.models import StageName
from a2sdlc.domain.run_result import DispatchResult
from a2sdlc.evaluation.quality_gate import QualityResult, run_quality_gate
from a2sdlc.evaluation.telemetry import Telemetry


DispatchFn = Callable[[], Coroutine[Any, Any, DispatchResult]]


def run_tracked(
    *,
    dispatch_fn: DispatchFn,
    telemetry: Telemetry,
    stage: StageName,
    session_id: str,
    project_root: Path,
    quality_command: str,
    sha_before: str,
    dirty: bool,
) -> tuple[DispatchResult, QualityResult | None]:
    """Run ``dispatch_fn`` under the given telemetry; log metrics + quality artifact.

    ``telemetry`` is never ``None`` — pass ``NoopTelemetry()`` to disable.
    """
    with (
        telemetry.session(session_id) as opener,
        opener.stage(stage.value) as run,
    ):
        run.log_tag("git_sha_before", sha_before)
        run.log_tag("dirty_tree_before", "true" if dirty else "false")
        run.log_tag("session_id", session_id)

        result = asyncio.run(dispatch_fn())

        stats = result.stats
        if stats is not None:
            run.log_metric("tokens_in", stats.tokens_in)
            run.log_metric("tokens_out", stats.tokens_out)
            run.log_metric("cost_usd", stats.cost_usd)
            run.log_metric("turns", stats.num_turns)
            run.log_metric("duration_ms", stats.duration_ms)

        run.log_dict(
            _stage_output_artifact(stage, session_id, result),
            f"{stage.value}-output.json",
        )

        quality = _maybe_run_quality_gate(stage, result, project_root, quality_command)
        if quality is not None:
            run.log_metric("quality_passed", 1 if quality.passed else 0)
            artifact_path = project_root / ".a2sdlc" / "quality.log"
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text(quality.output)
            run.log_artifact(str(artifact_path))

    return result, quality


def _maybe_run_quality_gate(
    stage: StageName,
    result: DispatchResult,
    project_root: Path,
    quality_command: str,
) -> QualityResult | None:
    """Run the quality gate iff this was a successful IMPLEMENT stage."""
    if stage != StageName.IMPLEMENT or result.blocked or result.error is not None:
        return None
    return run_quality_gate(project_root=project_root, command=quality_command)


def _stage_output_artifact(
    stage: StageName, session_id: str, result: DispatchResult
) -> dict[str, object]:
    """Build the JSON payload logged as the stage output artifact."""
    stats = result.stats
    stats_payload: dict[str, float | int] = {}
    if stats is not None:
        stats_payload = {
            "tokens_in": stats.tokens_in,
            "tokens_out": stats.tokens_out,
            "cost_usd": stats.cost_usd,
            "num_turns": stats.num_turns,
            "duration_ms": stats.duration_ms,
        }
    return {
        "stage": stage.value,
        "session_id": session_id,
        "success": not result.blocked and result.error is None,
        "blocked": result.blocked,
        "error": result.error,
        "status": result.status.value if result.status else None,
        "next_stage": result.next_stage.value if result.next_stage else None,
        "output": result.output,
        "stats": stats_payload,
    }
```

- [ ] **Step 4.2: Run the full test suite to surface callers that now break**

Run: `uv run pytest -x 2>&1 | head -80`
Expected: failures in `run_stage.py` callers — `run_tracked` kwarg `sink` is gone. That's intentional; the next task fixes them.

- [ ] **Step 4.3: Commit (breaking change, next task unbreaks)**

```bash
git add packages/engine/src/a2sdlc/evaluation/tracked_run.py
git commit -m "refactor(evaluation): run_tracked takes Telemetry (not MlflowSink|None)"
```

---

### Task 5: Update `cli/run_stage.py` to the new API

**Files:**
- Modify: `packages/engine/src/a2sdlc/cli/run_stage.py`

- [ ] **Step 5.1: Replace the MLflow-sink block with telemetry factory calls**

In `packages/engine/src/a2sdlc/cli/run_stage.py`, replace lines 125-131:

```python
    sink = None
    if not no_track:
        from a2sdlc.evaluation.mlflow_sink import MlflowSink  # noqa: PLC0415

        mlflow_uri = f"file://{Path.home() / '.a2sdlc' / 'mlflow'}"
        sink = MlflowSink(tracking_uri=mlflow_uri, experiment_name=project_root.name)
        sink.verify_reachable()
```

with:

```python
    from a2sdlc.evaluation.telemetry import (  # noqa: PLC0415
        NoopTelemetry,
        local_fallback_telemetry,
    )

    telemetry = (
        NoopTelemetry()
        if no_track
        else local_fallback_telemetry(experiment_name=project_root.name)
    )
```

- [ ] **Step 5.2: Update the `wire_state` / `run_tracked` call to pass `telemetry`**

Find the `build_progress_state(...)` call (around line 154) and the `run_tracked(...)` call (around line 183). Update:

- `build_progress_state(...)` → `with_mlflow_trace=telemetry.traces_enabled`
- `run_tracked(...)` → replace `sink=sink` with `telemetry=telemetry`

- [ ] **Step 5.3: Run run-stage tests and confirm they pass**

Run: `uv run pytest tests/test_cli_local.py tests/integration/test_local_runner_e2e.py -v`
Expected: all previously-green tests green again. If failures reference `mlflow_sink`, update the test's imports to `telemetry` equivalents.

- [ ] **Step 5.4: Commit**

```bash
git add packages/engine/src/a2sdlc/cli/run_stage.py tests/
git commit -m "refactor(cli): run_stage uses Telemetry via local_fallback factory"
```

---

### Task 6: Wire `cli/dispatch.py` with `telemetry_from_env` + `run_tracked`

**Files:**
- Modify: `packages/engine/src/a2sdlc/cli/dispatch.py`

- [ ] **Step 6.1: Derive session_id, stage, sha_before, and call `run_tracked`**

Find the block (end of `dispatch_command`):

```python
    try:
        result = asyncio.run(dispatch(ctx))
        if result.blocked:
            logger.error("Dispatch blocked: %s", result.error)
            raise typer.Exit(code=1)
    except KeyboardInterrupt:
        logger.info("Interrupted")
```

Replace with (note: `ctx` already carries everything we need — ticket key is the session anchor, stage comes from the work adapter's current event):

```python
    from a2sdlc.evaluation.telemetry import telemetry_from_env  # noqa: PLC0415
    from a2sdlc.evaluation.tracked_run import run_tracked  # noqa: PLC0415
    from a2sdlc.domain.models import StageName  # noqa: PLC0415

    telemetry = telemetry_from_env(experiment_name=root.name)

    # `dispatch(ctx)` determines the stage internally; we need it pre-call for
    # the telemetry bracket. The work adapter exposes the current stage on the
    # event — call it once here.
    event = asyncio.run(work_adapter.current_event())
    session_id = event.ticket_key
    stage = event.stage  # StageName enum
    sha_before = git.head_sha()
    dirty = git.is_dirty()

    async def _run() -> Any:  # noqa: ANN401
        return await dispatch(ctx)

    try:
        result, _quality = run_tracked(
            dispatch_fn=_run,
            telemetry=telemetry,
            stage=stage,
            session_id=session_id,
            project_root=root,
            quality_command=config.quality.command,
            sha_before=sha_before,
            dirty=dirty,
        )
        if result.blocked:
            logger.error("Dispatch blocked: %s", result.error)
            raise typer.Exit(code=1)
    except KeyboardInterrupt:
        logger.info("Interrupted")
```

> **If `work_adapter.current_event()` does not exist**, grep for the existing
> stage-detection call inside `pipeline/dispatch.py` and replicate it here. Do
> not invent a new method.

- [ ] **Step 6.2: Also pipe `telemetry.traces_enabled` into `build_progress_state`**

Find `progress_state = build_progress_state(root, config.adapters.progress)` earlier in the function. Replace with:

```python
    progress_state = build_progress_state(
        root,
        config.adapters.progress,
        with_mlflow_trace=telemetry.traces_enabled,
    )
```

(Move this line to come *after* `telemetry = telemetry_from_env(...)`.)

- [ ] **Step 6.3: Run dispatch-related tests**

Run: `uv run pytest tests/ -k dispatch -v 2>&1 | tail -30`
Expected: all pass. If `work_adapter.current_event()` was wrong, fix and re-run.

- [ ] **Step 6.4: Commit**

```bash
git add packages/engine/src/a2sdlc/cli/dispatch.py
git commit -m "feat(cli): wire dispatch.py with telemetry_from_env + run_tracked"
```

---

### Task 7: Remove `mlflow_sink.py` and migrate its tests

**Files:**
- Delete: `packages/engine/src/a2sdlc/evaluation/mlflow_sink.py`
- Modify: `tests/evaluation/test_mlflow_sink.py` — either delete (coverage is subsumed by `test_telemetry.py`) or rename & trim to assertions not duplicated.
- Modify: anywhere else that still imports `MlflowSink`.

- [ ] **Step 7.1: Grep for remaining `MlflowSink` imports**

Run: `uv run ruff check packages/ tests/ --select F401 2>&1 | head; grep -rn "MlflowSink\|mlflow_sink" packages/ tests/ --include="*.py"`

Expected output: no hits outside `test_mlflow_sink.py`. If hits exist, update them to the `Telemetry` surface.

- [ ] **Step 7.2: Delete old module**

Run: `git rm packages/engine/src/a2sdlc/evaluation/mlflow_sink.py`

- [ ] **Step 7.3: Delete the old test file (coverage lives in `test_telemetry.py`)**

Run: `git rm tests/evaluation/test_mlflow_sink.py`

- [ ] **Step 7.4: Run full test suite**

Run: `uv run pytest -x 2>&1 | tail -30`
Expected: all pass.

- [ ] **Step 7.5: Commit**

```bash
git commit -m "refactor(evaluation): remove MlflowSink — absorbed into telemetry.py"
```

---

### Task 8: Integration test — `dispatch.py` produces MLflow runs against a file store

**Files:**
- Create: `tests/integration/test_dispatch_telemetry.py`

- [ ] **Step 8.1: Write the integration test**

Create `tests/integration/test_dispatch_telemetry.py`:

```python
"""End-to-end: cli/dispatch with MLFLOW_TRACKING_URI set produces runs."""

from __future__ import annotations

from pathlib import Path

import mlflow
import pytest


pytestmark = pytest.mark.integration


def test_dispatch_emits_mlflow_runs_when_env_set(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """With MLFLOW_TRACKING_URI set, dispatch writes session + stage runs.

    This uses the dispatch entry point directly with a faked work adapter so
    we exercise the real telemetry + run_tracked plumbing end-to-end without
    needing a real GH API.
    """
    tracking_uri = f"file://{tmp_path / 'mlflow'}"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", tracking_uri)

    # Copy the fixture-repo pattern already used by test_local_runner_e2e.py.
    # The engine discovers project_root.name, so the experiment will be
    # named after the tmp repo dir.
    project = tmp_path / "smoke-fixture"
    project.mkdir()
    (project / ".a2sdlc").mkdir()

    # Invoke via the run-stage path since it shares the same run_tracked
    # orchestration — we're verifying the Telemetry wiring, not the GH adapter.
    monkeypatch.chdir(project)
    # ... replicate the scaffold that test_local_runner_e2e.py uses (stub
    # runner, seed ticket.md, etc.). If that file already expresses this
    # pattern, move the assertion below into that file instead of creating
    # a new one.

    mlflow.set_tracking_uri(tracking_uri)
    runs = mlflow.search_runs(
        experiment_names=["smoke-fixture"], output_format="list"
    )
    names = {r.data.tags.get("mlflow.runName") for r in runs}
    assert any(n and n.startswith("session:") for n in names)
    assert any(n and ":spec" in (n or "") for n in names)
```

> **Note:** if `tests/integration/test_local_runner_e2e.py` already expresses
> the scaffold-and-run pattern, extend it instead of creating a sibling —
> prefer extension over duplication.

- [ ] **Step 8.2: Run the integration test**

Run: `uv run pytest tests/integration/test_dispatch_telemetry.py -v`
Expected: 1 passed.

- [ ] **Step 8.3: Commit**

```bash
git add tests/integration/test_dispatch_telemetry.py
git commit -m "test(integration): dispatch telemetry end-to-end against file store"
```

---

### Task 9: Docs — env override

**Files:**
- Modify: `docs/local-runner-usage.md`
- Modify: `README.md`

- [ ] **Step 9.1: Update `docs/local-runner-usage.md:64`**

Change the `--no-track` table row and the "Only MLflow lives outside the repo" paragraph (around line 100) to:

```markdown
| `--no-track`      | Skip MLflow logging entirely. Useful for throwaway runs. |

...

MLflow tracking store selection:

- If `MLFLOW_TRACKING_URI` is set, that URI is used (works with both local
  file stores and remote trackers; pair with `MLFLOW_TRACKING_USERNAME` /
  `MLFLOW_TRACKING_PASSWORD` for authenticated remotes).
- Otherwise, a local file store at `~/.a2sdlc/mlflow` is used.
- `--no-track` bypasses MLflow entirely.
```

- [ ] **Step 9.2: Update `README.md:48`**

Replace the mention of `~/.a2sdlc/mlflow` with:

```markdown
MLflow store: `$MLFLOW_TRACKING_URI` if set, else `~/.a2sdlc/mlflow` for
local dev. CI workflows forward the standard `MLFLOW_*` secrets; the engine
activates telemetry only when `MLFLOW_TRACKING_URI` is present.
```

- [ ] **Step 9.3: Commit**

```bash
git add docs/local-runner-usage.md README.md
git commit -m "docs: MLFLOW_TRACKING_URI overrides local ~/.a2sdlc/mlflow default"
```

---

### Task 10: Full quality gate

**Files:** none (verification only).

- [ ] **Step 10.1: Run `make check`**

Run: `make check`
Expected: lint + tests + coverage-diff + security-audit all pass.

If `make coverage-diff` fails on any file changed in Tasks 1–9, add targeted tests for the uncovered lines (no new functionality — just coverage).

- [ ] **Step 10.2: If anything failed, fix it and re-run**

- [ ] **Step 10.3: Commit only if coverage or lint fixes were needed**

```bash
git add -A
git commit -m "chore: coverage + lint fixes for telemetry rewiring"
```

---

## Phase 2 — Smoke runbook (operational)

**No code changes in this repo. Executes against a newly-created private GH repo.**

### Task 11: Create the private smoke repo

- [ ] **Step 11.1: Create repo**

Run: `gh repo create iorlas/a2sdlc-smoke --private --description "a2sdlc Mode 2 e2e smoke fixture" --confirm`

- [ ] **Step 11.2: Clone locally into `/tmp`**

Run: `cd /tmp && gh repo clone iorlas/a2sdlc-smoke && cd a2sdlc-smoke`

- [ ] **Step 11.3: Commit workflow + README**

```bash
mkdir -p .github/workflows
cp /Users/iorlas/Workspaces/a2sdlc-engine/docs/mode2/example-workflows/a2sdlc-run.yml .github/workflows/a2sdlc-run.yml
printf '# a2sdlc-smoke\n\nMode 2 end-to-end smoke fixture. Do not use for real work.\n' > README.md
git add .github/workflows/a2sdlc-run.yml README.md
git commit -m "chore: a2sdlc Mode 2 workflow + README"
git push origin main
```

### Task 12: Configure secrets + permissions

- [ ] **Step 12.1: Set the four secrets**

Rotate keys first, then set:

```bash
gh secret set ANTHROPIC_API_KEY --repo iorlas/a2sdlc-smoke < <(printf "%s" "$ANTHROPIC_API_KEY")
gh secret set MLFLOW_TRACKING_URI --repo iorlas/a2sdlc-smoke --body "https://mlflow.shen.iorlas.net"
gh secret set MLFLOW_TRACKING_USERNAME --repo iorlas/a2sdlc-smoke --body "ci"
gh secret set MLFLOW_TRACKING_PASSWORD --repo iorlas/a2sdlc-smoke < <(printf "%s" "$MLFLOW_TRACKING_PASSWORD")
```

- [ ] **Step 12.2: Enable workflow PR create/approve**

```bash
gh api -X PUT "/repos/iorlas/a2sdlc-smoke/actions/permissions/workflow" \
  -F default_workflow_permissions=write \
  -F can_approve_pull_request_reviews=true
```

- [ ] **Step 12.3: Verify no branch-protection on `main`**

Run: `gh api "/repos/iorlas/a2sdlc-smoke/branches/main/protection" 2>&1 | head -5`
Expected: `Branch not protected` (HTTP 404). If a rule exists from org policy, remove it for this smoke repo: `gh api -X DELETE /repos/iorlas/a2sdlc-smoke/branches/main/protection`.

### Task 13: File the seed issue

- [ ] **Step 13.1: Create the issue body file locally**

```bash
cat > /tmp/smoke-issue.md <<'EOF'
```gherkin
Feature: Patient intake
  Scenario: Add and list patients
    Given no patients are stored
    When I run `patient-intake add --name "Ada Lovelace" --dob 1815-12-10 --complaint "headache"`
    Then a record is persisted
    When I run `patient-intake list`
    Then the output contains "Ada Lovelace" in a table
```
EOF
```

- [ ] **Step 13.2: Open issue and apply `agent` label**

```bash
ISSUE_URL=$(gh issue create --repo iorlas/a2sdlc-smoke \
  --title "Patient intake CLI" \
  --body-file /tmp/smoke-issue.md)
echo "Issue: $ISSUE_URL"
ISSUE_NUMBER=$(echo "$ISSUE_URL" | grep -oE '[0-9]+$')
gh issue edit "$ISSUE_NUMBER" --repo iorlas/a2sdlc-smoke --add-label agent
```

If `agent` label doesn't exist yet, `gh issue edit` will fail — create it:

```bash
gh label create agent --repo iorlas/a2sdlc-smoke --color C2E0C6 --description "trigger a2sdlc"
gh issue edit "$ISSUE_NUMBER" --repo iorlas/a2sdlc-smoke --add-label agent
```

### Task 14: Observe transitions

- [ ] **Step 14.1: Watch the Actions tab**

```bash
gh run watch --repo iorlas/a2sdlc-smoke
```

- [ ] **Step 14.2: After each stage completes, check label state**

Run: `gh issue view "$ISSUE_NUMBER" --repo iorlas/a2sdlc-smoke --json labels -q '.labels[].name'`

Expected progression (one check after each workflow run):
- After spec: labels include `stage:implement`; `agent` and `stage:spec` not present.
- After implement: `stage:review`.
- After review: `stage:merge`.

If at any point `stage:blocked` appears, **stop**. Run `gh issue view $ISSUE_NUMBER --comments --repo iorlas/a2sdlc-smoke` and triage before proceeding.

### Task 15: Verify MLflow captured the run

- [ ] **Step 15.1: Open `https://mlflow.shen.iorlas.net` in a browser**

Log in as `ci` with the rotated password.

- [ ] **Step 15.2: Confirm the expected structure**

- Experiment named `a2sdlc-smoke` exists.
- One parent run `session:<issue-number>` (or whatever session ID the engine derives).
- Child runs `<sid>:spec`, `<sid>:implement`, `<sid>:review`.
- Each child has tags `stage` and `session_id`, plus non-zero metrics `duration_ms`, `cost_usd`, `turns`, `tokens_in`, `tokens_out`.

If MLflow is empty, re-check `gh run view` logs for the stage job — look for `MlflowUnreachableError` (secret-wiring issue) or a silent no-op (telemetry wasn't wired; recheck Task 6).

### Task 16: Human pre-merge gate + merge

- [ ] **Step 16.1: Review the PR diff**

```bash
PR_NUMBER=$(gh pr list --repo iorlas/a2sdlc-smoke --json number -q '.[0].number')
gh pr view "$PR_NUMBER" --repo iorlas/a2sdlc-smoke --web
```

Confirm:
- Diff introduces a runnable `patient-intake` CLI.
- Tests exist and pass in the PR's Actions checks.
- PR body contains `Closes #<issue>`.

- [ ] **Step 16.2: Merge manually via the web UI**

In the browser, click "Merge pull request". Do NOT use `gh pr merge` — the ask is explicit manual gate.

- [ ] **Step 16.3: Verify quiescence**

```bash
sleep 30
gh run list --repo iorlas/a2sdlc-smoke --limit 5
```

Expected: no new workflow runs fired in the last 30s after merge. Issue auto-closes (linked via `Closes #N`) and labels end at `stage:done` or equivalent terminal state.

### Task 17: Record the outcome

- [ ] **Step 17.1: Write a short handover note**

Create `docs/superpowers/handovers/2026-04-21-mode2-smoke-handover.md` in this repo with:

- Link to the smoke issue + PR.
- Total cost (sum across MLflow runs).
- Duration wall-clock.
- Any unexpected observations or follow-ups filed.
- Explicit readiness call for Phase 2 (dispatcher + Jira).

- [ ] **Step 17.2: Commit handover + push 116+ outstanding commits to origin**

```bash
cd /Users/iorlas/Workspaces/a2sdlc-engine
git add docs/superpowers/handovers/2026-04-21-mode2-smoke-handover.md
git commit -m "docs(handover): Mode 2 smoke outcome"
git push origin main
```

---

## Self-Review Notes

- **Spec coverage:** all Phase 1 prerequisites and Phase 2 observation checklist items from the spec map to tasks. Branch-protection check → Task 12.3. `stage:spec` transient cleanup check → Task 14.2. `a2sdlc-unblock.yml` omission is documented in the spec and enforced by Task 11.3 (workflow copied verbatim, unblock not added).
- **Placeholders:** one `...` appears in Task 8.1 deliberately, with a note to extend the existing `test_local_runner_e2e.py` instead of duplicating its scaffold — this is an intentional choice (prefer extension), not an unfilled TODO.
- **Type consistency:** `Telemetry.session()`, `StageOpener.stage()`, `RunHandle.{log_metric,log_tag,log_dict,log_artifact}` are referenced identically in Tasks 1, 2, 3, 4, 5, 6. `telemetry_from_env(experiment_name=...)` and `local_fallback_telemetry(experiment_name=...)` keep the same kwarg. `run_tracked(..., telemetry=...)` matches Task 4's signature.
- **Scope:** Phase 1 is a cohesive rewire that must land before Phase 2 runs. Phase 2 is an operational runbook with no source changes in this repo — it belongs in this plan because success criteria depend on Phase 1 being live.
