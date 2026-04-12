"""Dispatch v2 integration tests."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from a2sdlc.adapters.work import PipelineEvent
from a2sdlc.config import ProjectConfig
from a2sdlc.dispatch import DispatchContext, dispatch
from a2sdlc.models import StageName, StageStatus
from a2sdlc.runner import RunResult
from tests.fakes_v2 import (
    FakeGitAdapter,
    FakeReviewAdapter,
    FakeRunner,
    FakeWorkAdapter,
)

_COMPLETE_OUTPUT = '```a2sdlc\n{"status": "complete", "ticket_summary": "Done"}\n```'
_APPROVED_OUTPUT = '```a2sdlc\n{"status": "approved", "ticket_summary": "LGTM"}\n```'


def _ctx(
    stage: StageName = StageName.SPEC,
    output: str = _COMPLETE_OUTPUT,
    ticket_body: str = "Build patient form",
    run_id: str | None = "run-1",
    results: list[RunResult] | None = None,
) -> tuple[
    DispatchContext, FakeWorkAdapter, FakeGitAdapter, FakeReviewAdapter, FakeRunner
]:
    event = PipelineEvent(key="35", stage=stage)
    work = FakeWorkAdapter(event=event, ticket_body=ticket_body, labels=None)
    git = FakeGitAdapter()
    review = FakeReviewAdapter()
    result_list = results or [
        RunResult(
            success=True,
            output=output,
            total_cost_usd=0.5,
            input_tokens=1000,
            output_tokens=2000,
            duration_ms=5000,
            num_turns=10,
        )
    ]
    runner = FakeRunner(result_list)
    config = ProjectConfig()
    ctx = DispatchContext(
        work=work,
        git=git,
        review=review,
        runner=runner,
        config=config,
        project_root=Path("/tmp/test"),
        logger=logging.getLogger("test"),
        run_id=run_id,
    )
    return ctx, work, git, review, runner


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_spec_complete_transitions_to_implement(self) -> None:
        ctx, work, *_ = _ctx(stage=StageName.SPEC)
        result = await dispatch(ctx)
        assert result.stage == StageName.SPEC
        assert result.status == StageStatus.COMPLETE
        assert result.next_stage == StageName.IMPLEMENT

    @pytest.mark.asyncio
    async def test_exactly_one_comment_per_stage_run(self) -> None:
        ctx, work, *_ = _ctx(stage=StageName.SPEC)
        await dispatch(ctx)
        assert len(work.created_comments) == 1
        assert len(work.finalized_comments) == 1

    @pytest.mark.asyncio
    async def test_draft_pr_created_on_spec(self) -> None:
        ctx, _, _, review, _ = _ctx(stage=StageName.SPEC)
        await dispatch(ctx)
        assert len(review.created_prs) == 1
        assert review.created_prs[0][3] == "35"  # ticket_key

    @pytest.mark.asyncio
    async def test_state_written(self) -> None:
        ctx, _, git, *_ = _ctx(stage=StageName.SPEC)
        await dispatch(ctx)
        assert len(git.written_state) >= 1


class TestGates:
    @pytest.mark.asyncio
    async def test_merge_human_default(self) -> None:
        """Default merge gate is HUMAN — review approved should NOT set merge label."""
        ctx, work, *_ = _ctx(stage=StageName.REVIEW, output=_APPROVED_OUTPUT)
        result = await dispatch(ctx)
        assert result.status == StageStatus.APPROVED
        # Default gate is HUMAN, so next_stage should be None
        assert result.next_stage is None


class TestErrors:
    @pytest.mark.asyncio
    async def test_runner_failure_blocks(self) -> None:
        ctx, work, *_ = _ctx(
            stage=StageName.SPEC,
            results=[RunResult(success=False, error="timeout")],
        )
        result = await dispatch(ctx)
        assert result.blocked is True
        assert len(work.finalized_comments) == 1

    @pytest.mark.asyncio
    async def test_skip_event(self) -> None:
        ctx, *_ = _ctx(stage=StageName.SPEC)
        ctx.work = FakeWorkAdapter(event=None, ticket_body="", labels=None)
        result = await dispatch(ctx)
        assert result.error is not None


class TestDirectives:
    @pytest.mark.asyncio
    async def test_base_directive(self) -> None:
        ctx, _, git, *_ = _ctx(
            stage=StageName.SPEC,
            ticket_body="[a2sdlc base=develop]\n\nBuild form",
        )
        await dispatch(ctx)
        assert len(git.branch_setups) == 1
        _, base = git.branch_setups[0]
        assert base == "develop"

    @pytest.mark.asyncio
    async def test_directives_stripped_from_prompt(self) -> None:
        ctx, _, _, _, runner = _ctx(
            stage=StageName.SPEC,
            ticket_body="[a2sdlc base=develop]\n\nBuild form",
        )
        await dispatch(ctx)
        assert len(runner.calls) >= 1
        assert "[a2sdlc" not in runner.calls[0].user_prompt
