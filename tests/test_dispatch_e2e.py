"""End-to-end smoke tests for the full feedback/proceed pipeline."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from a2sdlc.adapters.review import Approval
from a2sdlc.adapters.work import PipelineEvent
from a2sdlc.config import ProjectConfig
from a2sdlc.dispatch import DispatchContext, dispatch
from a2sdlc.handover import FeedbackItem, HandoverComment
from a2sdlc.models import StageName
from a2sdlc.runner import RunResult
from tests.fakes import (
    FakeGitAdapter,
    FakeReviewAdapter,
    FakeRunner,
    FakeWorkAdapter,
)

_COMPLETE_OUTPUT = '```a2sdlc\n{"status": "complete", "output": "Done"}\n```'

_T1 = datetime(2026, 4, 10, tzinfo=timezone.utc)
_T2 = datetime(2026, 4, 11, tzinfo=timezone.utc)
_T3 = datetime(2026, 4, 12, tzinfo=timezone.utc)

_DEFAULT_RUN = RunResult(
    success=True,
    output=_COMPLETE_OUTPUT,
    total_cost_usd=0.5,
    input_tokens=1000,
    output_tokens=2000,
    duration_ms=5000,
    num_turns=10,
)


def _ho(stage: StageName, t: datetime) -> HandoverComment:
    return HandoverComment(
        stage=stage,
        run_id="r",
        body="done",
        created_at=t,
        location="issue",
    )


def _fb(body: str, t: datetime) -> FeedbackItem:
    return FeedbackItem(
        id="fb",
        author="human",
        author_type="human",
        source="issue_comment",
        body=body,
        created_at=t,
    )


def _feedback_ctx(
    *,
    issue_handover: HandoverComment | None = None,
    issue_feedback: list[FeedbackItem] | None = None,
) -> tuple[DispatchContext, FakeRunner]:
    event = PipelineEvent(key="42", is_feedback=True)
    work = FakeWorkAdapter(
        event=event,
        ticket_body="Build form",
        labels=None,
        last_handover=issue_handover,
        issue_feedback=issue_feedback or [],
    )
    runner = FakeRunner(_DEFAULT_RUN)
    ctx = DispatchContext(
        work=work,
        git=FakeGitAdapter(),
        review=FakeReviewAdapter(),
        runner=runner,
        config=ProjectConfig(),
        project_root=Path("/tmp/test"),
        logger=logging.getLogger("test"),
        run_id="run-e2e",
    )
    return ctx, runner


def _proceed_merge_ctx(pr_number: int = 7) -> tuple[DispatchContext, FakeReviewAdapter]:
    """Build a proceed context at the REVIEW stage with a PR ready to merge."""
    state = json.dumps(
        {
            "stage": "review",
            "status": "approved",
            "base_branch": "main",
            "branch": "agent/42",
            "pr_number": pr_number,
            "stage_run_id": "run-old",
            "review_cycles": 0,
            "accumulated_cost_usd": 0.0,
            "accumulated_tokens_in": 0,
            "accumulated_tokens_out": 0,
            "accumulated_duration_ms": 0,
            "last_updated": "2026-04-10T00:00:00Z",
        }
    )
    event = PipelineEvent(key="42", trigger_stage=None, is_feedback=False)
    work = FakeWorkAdapter(
        event=event,
        ticket_body="Build form",
        labels=None,
        last_handover=_ho(StageName.REVIEW, _T1),
    )
    git = FakeGitAdapter(state_json=state)
    # Provide a human approval so the HUMAN merge gate is satisfied
    review = FakeReviewAdapter(
        approvals=[Approval(user="human-reviewer", is_bot=False)]
    )
    runner = FakeRunner(_DEFAULT_RUN)
    ctx = DispatchContext(
        work=work,
        git=git,
        review=review,
        runner=runner,
        config=ProjectConfig(),
        project_root=Path("/tmp/test"),
        logger=logging.getLogger("test"),
        run_id="run-proceed-merge",
    )
    return ctx, review


class TestE2ESmokeTests:
    """End-to-end smoke tests that verify the full feedback/proceed pipeline."""

    @pytest.mark.asyncio
    async def test_feedback_cycle_executes_implement_with_feedback_in_prompt(
        self,
    ) -> None:
        """Full feedback cycle: IMPLEMENT stage runs and feedback text appears in user prompt."""
        feedback_text = "Please fix the validation logic"
        ctx, runner = _feedback_ctx(
            issue_handover=_ho(StageName.REVIEW, _T1),
            issue_feedback=[_fb(feedback_text, _T2)],
        )
        result = await dispatch(ctx)

        # IMPLEMENT stage was executed
        assert result.stage == StageName.IMPLEMENT
        assert len(runner.calls) == 1

        # Feedback text was passed through to the runner
        assert feedback_text in runner.calls[0].user_prompt

    @pytest.mark.asyncio
    async def test_proceed_at_merge_gate_actually_merges_pr(self) -> None:
        """Proceed event at REVIEW stage routes to MERGE and merges the PR."""
        ctx, review = _proceed_merge_ctx(pr_number=7)
        result = await dispatch(ctx)

        # MERGE stage executed without blocking
        assert result.stage == StageName.MERGE
        assert result.blocked is False

        # The PR was actually merged
        assert len(review.merged_prs) == 1
        assert review.merged_prs[0][0] == 7  # pr_number

    @pytest.mark.asyncio
    async def test_feedback_already_addressed_does_not_execute_stage(self) -> None:
        """Feedback dedup: when handover is newer than all feedback, no stage runs."""
        ctx, runner = _feedback_ctx(
            issue_handover=_ho(StageName.IMPLEMENT, _T3),
            issue_feedback=[_fb("Already handled", _T1)],
        )
        result = await dispatch(ctx)

        assert result.error == "feedback_already_addressed"
        assert len(runner.calls) == 0
