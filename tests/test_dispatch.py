"""Dispatch integration tests."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from a2sdlc.adapters.work import PipelineEvent
from a2sdlc.config import ProjectConfig
from a2sdlc.dispatch import DispatchContext, dispatch
from a2sdlc.models import StageName, StageStatus
from a2sdlc.runner import RunResult
from tests.fakes import (
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
    event = PipelineEvent(key="35", trigger_stage=stage)
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

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_after_max_review_cycles(self) -> None:
        """Review stage blocked when review_cycles exceed max."""
        import json

        state = {
            "stage": "review",
            "status": "changes_requested",
            "base_branch": "main",
            "branch": "agent/35",
            "pr_number": 1,
            "stage_run_id": "run-old",
            "review_cycles": 99,
            "accumulated_cost_usd": 0.0,
            "accumulated_tokens_in": 0,
            "accumulated_tokens_out": 0,
            "accumulated_duration_ms": 0,
            "last_updated": "2026-04-12T00:00:00Z",
        }
        ctx, work, git, *_ = _ctx(stage=StageName.REVIEW, run_id="run-new")
        git._state_json = json.dumps(state)
        result = await dispatch(ctx)
        assert result.blocked is True
        assert "Circuit breaker" in (result.error or "")

    @pytest.mark.asyncio
    async def test_git_blocked_returns_blocked(self) -> None:
        """Git branch setup failure blocks the dispatch."""
        ctx, work, *_ = _ctx(stage=StageName.SPEC)
        ctx.git = FakeGitAdapter(conflict_on_setup=True)
        result = await dispatch(ctx)
        assert result.blocked is True

    @pytest.mark.asyncio
    async def test_no_status_block_blocks(self) -> None:
        """No status block in output after follow-ups blocks."""
        no_block_output = "Some output with no status block."
        ctx, work, *_ = _ctx(
            stage=StageName.SPEC,
            results=[RunResult(success=True, output=no_block_output)] * 4,
        )
        result = await dispatch(ctx)
        assert result.blocked is True
        assert result.error == "no_status_block"


class TestReviewLoop:
    @pytest.mark.asyncio
    async def test_changes_requested_increments_review_cycles(self) -> None:
        """changes_requested status increments review_cycles in state."""
        changes_output = '```a2sdlc\n{"status": "changes_requested"}\n```'
        ctx, _, git, *_ = _ctx(stage=StageName.REVIEW, output=changes_output)
        result = await dispatch(ctx)
        assert result.status == StageStatus.CHANGES_REQUESTED
        assert result.next_stage == StageName.IMPLEMENT
        # State should have review_cycles = 1
        assert len(git.written_state) >= 1
        import json

        state = json.loads(git.written_state[-1])
        assert state["review_cycles"] == 1

    @pytest.mark.asyncio
    async def test_changes_requested_posts_review(self) -> None:
        """changes_requested posts REQUEST_CHANGES review on PR."""
        changes_output = '```a2sdlc\n{"status": "changes_requested"}\n```'
        event = PipelineEvent(key="35", trigger_stage=StageName.REVIEW, pr_number=42)
        work = FakeWorkAdapter(event=event, ticket_body="Review this", labels=None)
        git = FakeGitAdapter()
        review = FakeReviewAdapter()
        runner = FakeRunner(
            RunResult(
                success=True,
                output=changes_output,
                total_cost_usd=0.1,
                input_tokens=100,
                output_tokens=200,
                duration_ms=1000,
                num_turns=5,
            )
        )
        ctx = DispatchContext(
            work=work,
            git=git,
            review=review,
            runner=runner,
            config=ProjectConfig(),
            project_root=Path("/tmp/test"),
            logger=logging.getLogger("test"),
            run_id="run-review",
        )
        await dispatch(ctx)
        assert len(review.reviews) == 1
        assert review.reviews[0][2] == "REQUEST_CHANGES"


class TestAutoSpec:
    @pytest.mark.asyncio
    async def test_auto_spec_prepends_system_prompt(self) -> None:
        """auto_spec config injects 'do not ask questions' into system prompt."""
        ctx, _, _, _, runner = _ctx(stage=StageName.SPEC)
        ctx.config = ProjectConfig(auto_spec=True)
        await dispatch(ctx)
        assert len(runner.calls) >= 1
        assert "Do not ask questions" in runner.calls[0].system_prompt


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_duplicate_run_id_skips(self) -> None:
        """Duplicate run_id returns early without calling the runner."""
        import json

        state = {
            "stage": "spec",
            "status": "complete",
            "base_branch": "main",
            "branch": "agent/35",
            "stage_run_id": "run-1",
            "review_cycles": 0,
            "accumulated_cost_usd": 0.0,
            "accumulated_tokens_in": 0,
            "accumulated_tokens_out": 0,
            "accumulated_duration_ms": 0,
            "last_updated": "2026-04-12T00:00:00Z",
        }
        ctx, _, _, _, runner = _ctx(stage=StageName.SPEC, run_id="run-1")
        ctx.git = FakeGitAdapter(state_json=json.dumps(state))
        result = await dispatch(ctx)
        assert result.error == "duplicate_run_id"
        assert len(runner.calls) == 0


class TestStatsInFinalComment:
    @pytest.mark.asyncio
    async def test_final_comment_contains_cost(self) -> None:
        """Final comment includes cost stats from the run."""
        ctx, work, *_ = _ctx(stage=StageName.SPEC)
        await dispatch(ctx)
        assert len(work.finalized_comments) == 1
        final_body = work.finalized_comments[0][1]
        assert "$0.50" in final_body

    @pytest.mark.asyncio
    async def test_final_comment_contains_tokens(self) -> None:
        """Final comment includes token counts."""
        ctx, work, *_ = _ctx(stage=StageName.SPEC)
        await dispatch(ctx)
        final_body = work.finalized_comments[0][1]
        assert "1k in" in final_body
        assert "2k out" in final_body


class TestImplementUpdatingPR:
    @pytest.mark.asyncio
    async def test_implement_complete_updates_pr(self) -> None:
        """Implement complete with pr_title updates the PR."""
        impl_output = (
            '```a2sdlc\n{"status": "complete", "pr_title": "feat: patient form", '
            '"pr_summary": "Adds form"}\n```'
        )
        # Set up with existing state that has a pr_number
        import json

        state = {
            "stage": "spec",
            "status": "complete",
            "base_branch": "main",
            "branch": "agent/35",
            "pr_number": 1,
            "stage_run_id": "run-old",
            "review_cycles": 0,
            "accumulated_cost_usd": 0.0,
            "accumulated_tokens_in": 0,
            "accumulated_tokens_out": 0,
            "accumulated_duration_ms": 0,
            "last_updated": "2026-04-12T00:00:00Z",
        }
        ctx, _, git, review, _ = _ctx(
            stage=StageName.IMPLEMENT,
            output=impl_output,
            run_id="run-2",
        )
        git._state_json = json.dumps(state)
        result = await dispatch(ctx)
        assert result.status == StageStatus.COMPLETE
        # PR should have been updated with the title/summary
        assert len(review.updated_prs) == 1
        assert review.updated_prs[0][1] == "feat: patient form"

    @pytest.mark.asyncio
    async def test_implement_transitions_to_review_with_auto_gate(self) -> None:
        """Implement complete with review=AUTO transitions to review."""

        ctx, work, *_ = _ctx(stage=StageName.IMPLEMENT)
        ctx.config = ProjectConfig()
        # Default review gate is AUTO
        result = await dispatch(ctx)
        assert result.status == StageStatus.COMPLETE
        assert result.next_stage == StageName.REVIEW


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
