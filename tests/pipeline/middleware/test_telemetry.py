"""L1 tests for ``pipeline.middleware.telemetry.with_telemetry``.

Uses the fake adapters from ``tests/fakes.py`` so progress /
telemetry side effects can be observed without touching MLflow. Fake
``next_`` returns a canned ``DispatchResult`` so the middleware's
derivation of (success, error) from the result is pinned.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from a2sdlc.domain.models import StageName
from a2sdlc.domain.pipeline_event import PipelineEvent
from a2sdlc.domain.run_context import RunContext
from a2sdlc.domain.run_result import DispatchResult
from a2sdlc.pipeline.middleware import StageAttempt
from a2sdlc.pipeline.middleware.telemetry import with_telemetry
from tests.fakes import make_dispatch_context, populate_run_intent


def _ctx_with_stage_config(
    stage: StageName = StageName.SPEC,
) -> tuple[RunContext, Any]:
    event = PipelineEvent(key="99", trigger_stage=stage)
    ctx, _work, _git, _review, _runner = make_dispatch_context(
        event=event, project_root=Path("/tmp/test_with_telemetry")
    )
    intent = populate_run_intent(ctx)
    ctx.intent = intent
    # load_stage_config is called by dispatch before the middleware runs.
    from a2sdlc.config import load_stage_config  # noqa: PLC0415

    ctx.stage_config = load_stage_config(intent.target_stage.value, ctx.config)
    return ctx, intent


@pytest.mark.asyncio
async def test_passthrough_result_is_returned_unchanged() -> None:
    ctx, intent = _ctx_with_stage_config()
    canned = DispatchResult(stage=intent.target_stage, blocked=False)

    async def fake_next(_ctx: RunContext, _intent: Any) -> DispatchResult:
        return canned

    stack: StageAttempt = with_telemetry(fake_next)
    result = await stack(ctx, intent)
    assert result is canned


@pytest.mark.asyncio
async def test_ctx_run_is_populated_before_next_runs() -> None:
    ctx, intent = _ctx_with_stage_config()
    captured: dict[str, Any] = {}

    async def fake_next(inner_ctx: RunContext, _intent: Any) -> DispatchResult:
        captured["run"] = inner_ctx.run
        return DispatchResult(stage=intent.target_stage)

    await with_telemetry(fake_next)(ctx, intent)
    # NoopTelemetry yields a _NoopRun instance; what matters is that the
    # middleware assigns _something_ before `next_` is awaited.
    assert captured["run"] is not None


@pytest.mark.asyncio
async def test_stage_start_and_stage_end_called_on_happy_path() -> None:
    ctx, intent = _ctx_with_stage_config()
    events: list[str] = []

    class Recorder:
        async def handle(self, event: Any) -> None:
            events.append(type(event).__name__)

    ctx.progress_state.subscribe(Recorder())

    async def fake_next(_ctx: RunContext, _intent: Any) -> DispatchResult:
        return DispatchResult(stage=intent.target_stage, blocked=False)

    await with_telemetry(fake_next)(ctx, intent)
    # Both envelope events fired.
    assert "StageStart" in events
    assert "StageEnd" in events


@pytest.mark.asyncio
async def test_stage_end_derives_success_false_from_blocked_result() -> None:
    ctx, intent = _ctx_with_stage_config()
    observed: dict[str, Any] = {}

    class StageEndRecorder:
        async def handle(self, event: Any) -> None:
            if type(event).__name__ == "StageEnd":
                observed["success"] = event.success
                observed["error"] = event.error

    ctx.progress_state.subscribe(StageEndRecorder())

    async def fake_next(_ctx: RunContext, _intent: Any) -> DispatchResult:
        return DispatchResult(stage=intent.target_stage, blocked=True, error="boom")

    await with_telemetry(fake_next)(ctx, intent)
    assert observed["success"] is False
    assert observed["error"] == "boom"


@pytest.mark.asyncio
async def test_stage_end_fires_even_if_next_raises() -> None:
    ctx, intent = _ctx_with_stage_config()
    end_fired = False

    class StageEndRecorder:
        async def handle(self, event: Any) -> None:
            nonlocal end_fired
            if type(event).__name__ == "StageEnd":
                end_fired = True

    ctx.progress_state.subscribe(StageEndRecorder())

    async def fake_next(_ctx: RunContext, _intent: Any) -> DispatchResult:
        raise RuntimeError("handler crashed")

    with pytest.raises(RuntimeError, match="handler crashed"):
        await with_telemetry(fake_next)(ctx, intent)
    assert end_fired is True
