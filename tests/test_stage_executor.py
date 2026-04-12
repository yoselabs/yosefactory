"""Tests for StageExecutor — follow-up prompt logic, stat accumulation, error handling."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from a2sdlc.config import StageConfig
from a2sdlc.models import StageName, StageStatus
from a2sdlc.runner import RunResult
from tests.fakes_v2 import FakeRunner


# ── Helpers ──────────────────────────────────────────────────────────


def _cfg() -> StageConfig:
    return StageConfig(name="spec")


def _success_with_block(status: str = "complete") -> RunResult:
    return RunResult(
        success=True,
        output=f'Done.\n\n```a2sdlc\n{{"status": "{status}"}}\n```',
        input_tokens=1000,
        output_tokens=500,
        total_cost_usd=0.05,
        duration_ms=30_000,
        num_turns=3,
    )


def _success_no_block() -> RunResult:
    return RunResult(
        success=True,
        output="Some output with no status block.",
        input_tokens=500,
        output_tokens=200,
        total_cost_usd=0.02,
        duration_ms=10_000,
        num_turns=2,
    )


def _failure(error: str = "sdk_error") -> RunResult:
    return RunResult(
        success=False,
        output="",
        error=error,
        input_tokens=100,
        output_tokens=0,
        total_cost_usd=0.01,
        duration_ms=5_000,
        num_turns=0,
    )


async def _run(
    runner: FakeRunner,
    on_progress: Callable[[str], None] | None = None,
):  # noqa: ANN202
    from a2sdlc.stage_executor import StageExecutor

    executor = StageExecutor(runner)
    return await executor.run(
        user_prompt="Do the work.",
        system_prompt="You are helpful.",
        config=_cfg(),
        ticket_key="PROJ-1",
        stage=StageName.SPEC,
        project_root="/repo",
        is_resume=False,
        on_progress=on_progress,
        branch="main",
    )


# ── Tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_block_on_first_try():
    """Agent produces status block on first try — single call, result populated."""
    runner = FakeRunner(_success_with_block("complete"))
    result = await _run(runner)

    assert result.success is True
    assert result.stage_result is not None
    assert result.stage_result.status == StageStatus.COMPLETE
    assert len(runner.calls) == 1


@pytest.mark.asyncio
async def test_no_block_sends_followup_as_resume():
    """No status block → follow-up sent with is_resume=True."""
    runner = FakeRunner([_success_no_block(), _success_with_block("complete")])
    await _run(runner)

    assert len(runner.calls) == 2
    assert runner.calls[1].is_resume is True


@pytest.mark.asyncio
async def test_followup_populates_stage_result():
    """Follow-up response contains status block → stage_result populated."""
    runner = FakeRunner([_success_no_block(), _success_with_block("questions")])
    result = await _run(runner)

    assert result.stage_result is not None
    assert result.stage_result.status == StageStatus.QUESTIONS


@pytest.mark.asyncio
async def test_all_followups_fail_returns_none_stage_result():
    """All 3 follow-ups produce no status block → stage_result is None, 4 total calls."""
    runner = FakeRunner(
        [_success_no_block()] * 4  # initial + 3 follow-ups, all without block
    )
    result = await _run(runner)

    assert result.stage_result is None
    assert len(runner.calls) == 4  # 1 initial + 3 follow-ups


@pytest.mark.asyncio
async def test_stats_accumulated_across_calls():
    """Stats accumulate correctly across initial + follow-up calls."""
    first = _success_no_block()  # cost=0.02, in=500, out=200, dur=10_000, turns=2
    second = _success_with_block()  # cost=0.05, in=1000, out=500, dur=30_000, turns=3

    runner = FakeRunner([first, second])
    result = await _run(runner)

    stats = result.stats
    assert abs(stats.cost_usd - 0.07) < 1e-9
    assert stats.tokens_in == 1500
    assert stats.tokens_out == 700
    assert stats.duration_ms == 40_000
    assert stats.num_turns == 5


@pytest.mark.asyncio
async def test_runner_failure_returns_error_result():
    """Runner returns failure → ExecutionResult.success=False, error populated."""
    runner = FakeRunner(_failure("timeout"))
    result = await _run(runner)

    assert result.success is False
    assert result.error == "timeout"
    assert result.stage_result is None


@pytest.mark.asyncio
async def test_on_progress_wired_through():
    """on_progress callback passed through to runner."""
    called: list[str] = []

    def _progress(msg: str) -> None:
        called.append(msg)

    runner = FakeRunner(_success_with_block())
    await _run(runner, on_progress=_progress)

    assert runner.calls[0].on_progress is _progress


@pytest.mark.asyncio
async def test_followup_prompt_contains_handover_or_status():
    """Follow-up user_prompt mentions structured output."""
    runner = FakeRunner([_success_no_block(), _success_with_block()])
    await _run(runner)

    followup_prompt = runner.calls[1].user_prompt.lower()
    assert "handover" in followup_prompt or "status" in followup_prompt


@pytest.mark.asyncio
async def test_output_combines_all_runs():
    """ExecutionResult.output contains text from all runner calls."""
    first = _success_no_block()
    second = _success_with_block()

    runner = FakeRunner([first, second])
    result = await _run(runner)

    assert first.output in result.output
    assert second.output in result.output


@pytest.mark.asyncio
async def test_progress_state_from_last_result():
    """ExecutionResult.progress comes from the last runner result."""
    from a2sdlc.progress import ProgressState

    import time

    prog = ProgressState(
        model="claude-sonnet-4-6",
        branch="main",
        max_turns=25,
        context_window=200_000,
        project_root="/repo",
        start_time=time.time(),
    )
    second = _success_with_block()
    second.progress = prog

    runner = FakeRunner([_success_no_block(), second])
    result = await _run(runner)

    assert result.progress is prog


@pytest.mark.asyncio
async def test_milestones_from_progress_state():
    """ExecutionResult.milestones come from the last progress state."""
    from a2sdlc.progress import Milestone, ProgressState
    import time

    milestone = Milestone(timestamp=1.0, label="test milestone")
    prog = ProgressState(
        model="claude-sonnet-4-6",
        branch="main",
        max_turns=25,
        context_window=200_000,
        project_root="/repo",
        start_time=time.time(),
    )
    prog.milestones = [milestone]

    run_result = _success_with_block()
    run_result.progress = prog

    runner = FakeRunner(run_result)
    result = await _run(runner)

    assert milestone in result.milestones
