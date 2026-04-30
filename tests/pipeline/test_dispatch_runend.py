"""Tests for ``RunEnd`` emission in dispatch's finally block.

Spec §Console output cadence / AC #14: dispatch wraps the run loop in
try/finally and emits ``RunEnd`` on every terminal exit path — success,
handled failure (e.g. blocked), AND unhandled exception.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from a2sdlc.config import ProjectConfig
from a2sdlc.domain.models import StageName
from a2sdlc.domain.pipeline_event import PipelineEvent
from a2sdlc.domain.progress import ProgressState, RunEnd
from a2sdlc.domain.run_context import RunContext
from a2sdlc.domain.run_result import RunResult
from a2sdlc.pipeline.dispatch import dispatch
from tests.fakes import (
    FakeGitAdapter,
    FakeReviewAdapter,
    FakeRunner,
    FakeWorkAdapter,
    RecordingSubscriber,
    default_run_result,
)

_COMPLETE_OUTPUT = '```a2sdlc\n{"status": "complete", "output": "Done"}\n```'


def _make_ctx(
    *,
    runner: FakeRunner | None = None,
) -> tuple[RunContext, RecordingSubscriber]:
    event = PipelineEvent(key="35", trigger_stage=StageName.SPEC)
    work = FakeWorkAdapter(event=event, ticket_body="Build patient form")
    progress_state = ProgressState(project_root="/tmp/test")
    subscriber = RecordingSubscriber()
    progress_state.subscribe(subscriber)
    ctx = RunContext(
        work=work,
        git=FakeGitAdapter(),
        review=FakeReviewAdapter(),
        runner=runner or FakeRunner(default_run_result(_COMPLETE_OUTPUT)),
        progress_state=progress_state,
        config=ProjectConfig(),
        project_root=Path("/tmp/test"),
        logger=logging.getLogger("test"),
        run_id="run-end-1",
    )
    return ctx, subscriber


@pytest.mark.asyncio
async def test_dispatch_emits_runend_on_success() -> None:
    """Happy path: RunEnd is emitted with success=True, no error."""
    ctx, sub = _make_ctx()
    await dispatch(ctx)
    run_ends = [e for e in sub.events if isinstance(e, RunEnd)]
    assert len(run_ends) == 1, (
        f"expected exactly one RunEnd, got {[type(e).__name__ for e in sub.events]}"
    )
    re = run_ends[0]
    assert re.success is True
    assert re.error is None
    # workflow_id resolution must produce a non-empty identifier.
    assert re.workflow_id


@pytest.mark.asyncio
async def test_dispatch_runend_is_terminal_event() -> None:
    """RunEnd must be the LAST event in the stream (terminal)."""
    ctx, sub = _make_ctx()
    await dispatch(ctx)
    assert sub.events, "no events recorded"
    assert isinstance(sub.events[-1], RunEnd), (
        f"expected RunEnd last, got {type(sub.events[-1]).__name__}; "
        f"full: {[type(e).__name__ for e in sub.events]}"
    )


@pytest.mark.asyncio
async def test_emit_run_end_reads_aggregate_stats_from_state() -> None:
    """Unit-tests ``_emit_run_end`` directly: state.json shape with
    aggregate_stats + total_cycles is parsed into the RunEnd payload.
    Real state-loader lands in Task 17/18; for now we parse the v1
    fields best-effort.
    """
    import json

    from a2sdlc.domain.stats import StageRunStats
    from a2sdlc.pipeline.dispatch import _emit_run_end

    state = {
        "aggregate_stats": {
            "cost_usd": 1.25,
            "tokens_in": 500,
            "tokens_out": 800,
            "duration_ms": 9000,
            "num_turns": 7,
        },
        "total_cycles": {"spec": 1, "implement": 2, "bogus": 99},
    }
    ctx, sub = _make_ctx()
    ctx.git = FakeGitAdapter(state_json=json.dumps(state))
    await _emit_run_end(ctx, success=True, error=None)
    re = next(e for e in sub.events if isinstance(e, RunEnd))
    assert re.aggregate_stats == StageRunStats(
        cost_usd=1.25, tokens_in=500, tokens_out=800, duration_ms=9000, num_turns=7
    )
    # ``bogus`` is silently dropped (not a valid StageName).
    assert re.total_cycles == {StageName.SPEC: 1, StageName.IMPLEMENT: 2}


@pytest.mark.asyncio
async def test_emit_run_end_resilient_to_bad_state() -> None:
    """If state.json is corrupt, RunEnd still fires with default zeros."""
    from a2sdlc.pipeline.dispatch import _emit_run_end

    ctx, sub = _make_ctx()
    ctx.git = FakeGitAdapter(state_json="{not-json")
    await _emit_run_end(ctx, success=True, error=None)
    re = next(e for e in sub.events if isinstance(e, RunEnd))
    assert re.success is True
    assert re.aggregate_stats.cost_usd == 0
    assert re.total_cycles == {}


@pytest.mark.asyncio
async def test_emit_run_end_skips_when_progress_state_absent() -> None:
    """Defensive guard: dispatch can be called with progress_state=None
    in early-exit paths; RunEnd helper must short-circuit without raising.
    """
    from a2sdlc.pipeline.dispatch import _emit_run_end

    ctx, _ = _make_ctx()
    ctx.progress_state = None
    await _emit_run_end(ctx, success=True, error=None)  # must not raise


@pytest.mark.asyncio
async def test_emit_run_end_uses_pipelinerun_workflow_id_when_set() -> None:
    """``ctx.run.workflow_id`` wins over ``ctx.intent.branch`` for workflow_id."""
    from a2sdlc.domain.run_context import PipelineRun
    from a2sdlc.pipeline.dispatch import _emit_run_end

    ctx, sub = _make_ctx()
    ctx.run = PipelineRun(workflow_id="wf-canonical-id")
    await _emit_run_end(ctx, success=True, error=None)
    re = next(e for e in sub.events if isinstance(e, RunEnd))
    assert re.workflow_id == "wf-canonical-id"


@pytest.mark.asyncio
async def test_dispatch_runend_emit_failure_swallowed() -> None:
    """If the progress bus itself blows up while emitting RunEnd, dispatch
    must not propagate it — RunEnd is best-effort metadata."""

    class _BrokenProgress:
        def __init__(self) -> None:
            self.subscribed: list[object] = []

        def subscribe(self, sub: object) -> None:
            self.subscribed.append(sub)

        async def stage_start(self, *a: object, **kw: object) -> None: ...
        async def stage_end(self, *a: object, **kw: object) -> None: ...
        async def add_tool_call(self, *a: object, **kw: object) -> None: ...
        async def update_metrics(self, *a: object, **kw: object) -> None: ...
        async def add_milestone(self, *a: object, **kw: object) -> None: ...
        async def open_group(self, *a: object, **kw: object) -> None: ...
        async def close_group(self, *a: object, **kw: object) -> None: ...

        def snapshot_metrics(self):  # type: ignore[no-untyped-def]
            from a2sdlc.domain.progress import Metrics

            return Metrics(
                input_tokens=0,
                output_tokens=0,
                total_cost_usd=0.0,
                num_turns=0,
                elapsed=0.0,
            )

        async def run_end(self, **kw: object) -> None:
            raise RuntimeError("bus is on fire")

    ctx, _ = _make_ctx()
    ctx.progress_state = _BrokenProgress()
    # Should NOT raise — finally swallows.
    await dispatch(ctx)


@pytest.mark.asyncio
async def test_dispatch_emits_runend_on_unhandled_exception() -> None:
    """If dispatch raises, RunEnd still fires with success=False and error set."""

    class _BoomRunner(FakeRunner):
        async def run(  # type: ignore[override]
            self, *args: object, **kwargs: object
        ) -> RunResult:
            raise RuntimeError("kaboom")

    boom = _BoomRunner(default_run_result(_COMPLETE_OUTPUT))
    ctx, sub = _make_ctx(runner=boom)
    with pytest.raises(RuntimeError):
        await dispatch(ctx)
    run_ends = [e for e in sub.events if isinstance(e, RunEnd)]
    assert len(run_ends) == 1
    assert run_ends[0].success is False
    assert run_ends[0].error and "kaboom" in run_ends[0].error
