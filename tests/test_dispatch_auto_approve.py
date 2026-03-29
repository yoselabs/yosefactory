"""Tests for auto-approval retry when no status block is found."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from a2sdlc.adapters.protocols import DispatchInput
from a2sdlc.config import ProjectConfig
from a2sdlc.dispatch import DispatchContext, dispatch
from a2sdlc.models import StageName, StageStatus
from a2sdlc.runner import RunResult
from tests.fakes import FakeGitAdapter, FakeRunner, FakeTicketAdapter


def _success_output(status: str = "complete") -> str:
    return f'Done.\n\n```a2sdlc\n{{"status": "{status}"}}\n```'


def _success_result(status: str = "complete") -> RunResult:
    return RunResult(
        success=True,
        output=_success_output(status),
        input_tokens=1000,
        output_tokens=500,
        total_cost_usd=0.05,
        duration_ms=30000,
    )


def _no_status_result() -> RunResult:
    return RunResult(
        success=True,
        output="Does this design look right to you?",
        input_tokens=500,
        output_tokens=200,
        total_cost_usd=0.03,
        duration_ms=15000,
    )


def _make(
    *,
    result: RunResult | list[RunResult],
    auto_spec: bool = False,
) -> tuple[DispatchContext, FakeTicketAdapter, FakeRunner]:
    event = DispatchInput(key="T-1", stage=StageName.SPEC)
    tickets = FakeTicketAdapter(event=event, labels=[])
    git = FakeGitAdapter()
    runner = FakeRunner(result=result)
    ctx = DispatchContext(
        tickets=tickets,
        git=git,
        runner=runner,
        config=ProjectConfig(auto_spec=auto_spec),
        project_root=Path("/tmp/test"),
        logger=logging.getLogger("test.dispatch"),
    )
    return ctx, tickets, runner


@pytest.mark.unit
class TestAutoApprovalRetry:
    @pytest.mark.asyncio
    async def test_retries_with_resume_on_no_status_block(self) -> None:
        """auto_spec + no status block → resumes session with auto-approval."""
        ctx, tickets, runner = _make(
            result=[_no_status_result(), _success_result("complete")],
            auto_spec=True,
        )
        r = await dispatch(ctx)

        assert r.blocked is False
        assert r.status == StageStatus.COMPLETE
        # Two calls: initial + auto-approval resume
        assert len(runner.calls) == 2
        assert runner.calls[1].is_resume is True
        assert "Approved" in runner.calls[1].user_prompt

    @pytest.mark.asyncio
    async def test_no_retry_without_auto_spec(self) -> None:
        """Without auto_spec, no status block → blocked immediately."""
        ctx, tickets, runner = _make(
            result=_no_status_result(),
            auto_spec=False,
        )
        r = await dispatch(ctx)

        assert r.blocked is True
        assert r.error == "no_status_block"
        assert len(runner.calls) == 1

    @pytest.mark.asyncio
    async def test_gives_up_after_max_retries(self) -> None:
        """After max retries, blocks even with auto_spec."""
        ctx, tickets, runner = _make(
            result=_no_status_result(),  # always returns no status block
            auto_spec=True,
        )
        r = await dispatch(ctx)

        assert r.blocked is True
        assert r.error == "no_status_block"
        # 1 initial + 3 retries = 4 calls
        assert len(runner.calls) == 4
