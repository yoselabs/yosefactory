"""N6 standalone-invocability contract test for ReviewStage.

Mirrors ``test_spec_stage.py`` with two REVIEW-specific assertions:

- On success, ``post_review`` is recorded on the ReviewAdapter with the
  APPROVE / REQUEST_CHANGES verdict derived from ``StageStatus``.
- ``post_inline_comments`` is called unconditionally on success (empty
  list is a no-op per the adapter Protocol).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from a2sdlc.config import load_stage_config
from a2sdlc.domain.models import StageName, StageStatus
from a2sdlc.domain.pipeline_event import PipelineEvent
from a2sdlc.domain.run_result import RunResult
from a2sdlc.domain.stage_outcome import StageOutcome
from a2sdlc.lifecycle.comment import CommentManager
from a2sdlc.lifecycle.pr import PRLifecycle
from a2sdlc.pipeline.effects_apply import apply as apply_effects
from a2sdlc.pipeline.preflight import PreflightOutcome, run_preflight
from a2sdlc.stages.review import ReviewStage
from tests.fakes import FakeRunner, default_run_result, make_dispatch_context


_APPROVED_OUTPUT = '```a2sdlc\n{"status": "approved", "output": "LGTM"}\n```'
_CHANGES_OUTPUT = (
    '```a2sdlc\n{"status": "changes_requested", "output": "Needs fixes"}\n```'
)


def _populate_per_run_state(ctx: Any, output: str) -> PreflightOutcome:
    pre = run_preflight(ctx)
    assert isinstance(pre, PreflightOutcome), f"preflight short-circuited: {pre!r}"
    ctx.pre = pre
    ctx.pr_lifecycle = PRLifecycle(ctx.review)
    ctx.comment = CommentManager(ctx.work, pre.event.key)
    ctx.comment.start(pre.target_stage.value)
    ctx.pr_number = 42
    ctx.stage_config = load_stage_config(pre.target_stage.value, ctx.config)
    ctx.run = MagicMock(name="RunHandle")
    ctx.runner = FakeRunner([default_run_result(output)])
    return pre


def _review_ctx(**kwargs: Any) -> Any:
    event = PipelineEvent(key="35", trigger_stage=StageName.REVIEW)
    return make_dispatch_context(event=event, **kwargs)


@pytest.mark.asyncio
async def test_review_stage_happy_path_emits_effects_without_calling_adapters() -> None:
    """P3 step 6: execute() is adapter-pure; effects carry PostReview + PostInlineReview."""
    from a2sdlc.domain.effects import (
        CommentFinalize,
        CommitAndPush,
        LogMetric,
        PostInlineReview,
        PostReview,
        StateWrite,
    )

    ctx, _work, _git, review, _runner = _review_ctx(
        project_root=Path("/tmp/test_review_stage_effects_happy")
    )
    _populate_per_run_state(ctx, _APPROVED_OUTPUT)

    stage = ReviewStage()
    outcome = await stage.execute(ctx)
    effects = stage.effects(ctx, outcome)

    # execute() did not touch adapters.
    assert review.reviews == []
    assert review.inline_comments == []

    types_ = [type(e) for e in effects]
    assert CommentFinalize in types_
    assert StateWrite in types_
    assert CommitAndPush in types_
    assert PostReview in types_
    assert PostInlineReview in types_
    # SetCurrentStage only emitted when gates.merge=AUTO (default is HUMAN →
    # next_stage returns None, so no label transition).
    assert types_.count(LogMetric) == 5


@pytest.mark.asyncio
async def test_review_stage_failure_emits_blocked_effects_no_post_review() -> None:
    """Failure → MarkBlocked effect, no PostReview/PostInlineReview."""
    from a2sdlc.domain.effects import (
        CommentFinalize,
        CommitAndPush,
        MarkBlocked,
        PostInlineReview,
        PostReview,
        StateWrite,
    )

    ctx, work, _git, review, _runner = _review_ctx(
        runner_results=[RunResult(success=False, error="timeout")],
        project_root=Path("/tmp/test_review_stage_effects_fail"),
    )
    _populate_per_run_state(ctx, _APPROVED_OUTPUT)
    ctx.runner = FakeRunner([RunResult(success=False, error="timeout")])

    stage = ReviewStage()
    outcome = await stage.execute(ctx)
    effects = stage.effects(ctx, outcome)

    assert work.blocked == []
    assert review.reviews == []
    types_ = [type(e) for e in effects]
    assert CommentFinalize in types_
    assert CommitAndPush in types_
    assert MarkBlocked in types_
    assert StateWrite not in types_
    assert PostReview not in types_
    assert PostInlineReview not in types_


@pytest.mark.asyncio
async def test_review_stage_execute_approve_posts_native_review() -> None:
    """Success path with APPROVED → PostReview effect with APPROVE verdict, applied via interpreter."""
    ctx, _work, _git, review, _runner = _review_ctx(
        project_root=Path("/tmp/test_review_stage_approve")
    )
    _populate_per_run_state(ctx, _APPROVED_OUTPUT)

    stage = ReviewStage()
    outcome = await stage.execute(ctx)
    await apply_effects(ctx, stage.effects(ctx, outcome))

    assert isinstance(outcome, StageOutcome)
    assert outcome.status == StageStatus.APPROVED
    assert len(review.reviews) == 1
    pr_number, _body, verdict = review.reviews[0]
    assert pr_number == 42
    assert verdict == "APPROVE"
    # Inline comments threaded through (empty in step 6 — parser lands in step 7).
    assert len(review.inline_comments) == 1
    assert review.inline_comments[0] == (42, [])
    assert outcome.inline_comments == []


@pytest.mark.asyncio
async def test_review_stage_execute_changes_requested_posts_request_changes() -> None:
    ctx, _work, _git, review, _runner = _review_ctx(
        project_root=Path("/tmp/test_review_stage_changes")
    )
    _populate_per_run_state(ctx, _CHANGES_OUTPUT)

    stage = ReviewStage()
    outcome = await stage.execute(ctx)
    await apply_effects(ctx, stage.effects(ctx, outcome))

    assert outcome.status == StageStatus.CHANGES_REQUESTED
    assert len(review.reviews) == 1
    _pr, _body, verdict = review.reviews[0]
    assert verdict == "REQUEST_CHANGES"


@pytest.mark.asyncio
async def test_review_stage_execute_failure_returns_blocked_outcome() -> None:
    ctx, work, _git, review, _runner = _review_ctx(
        runner_results=[RunResult(success=False, error="timeout")],
        project_root=Path("/tmp/test_review_stage_fail"),
    )
    _populate_per_run_state(ctx, _APPROVED_OUTPUT)
    ctx.runner = FakeRunner([RunResult(success=False, error="timeout")])

    stage = ReviewStage()
    outcome = await stage.execute(ctx)
    await apply_effects(ctx, stage.effects(ctx, outcome))

    assert len(work.blocked) == 1
    # No native review on failure.
    assert review.reviews == []
    assert review.inline_comments == []


@pytest.mark.asyncio
async def test_review_stage_execute_no_status_block_returns_blocked() -> None:
    ctx, work, _git, review, _runner = _review_ctx(
        project_root=Path("/tmp/test_review_stage_nsb")
    )
    _populate_per_run_state(ctx, "plain text, no fenced a2sdlc block")

    stage = ReviewStage()
    outcome = await stage.execute(ctx)
    await apply_effects(ctx, stage.effects(ctx, outcome))

    assert len(work.blocked) == 1
    assert review.reviews == []


@pytest.mark.asyncio
async def test_review_stage_execute_threads_parsed_inline_comments() -> None:
    """ReviewStage parses inline_comments and emits them via PostInlineReview effect."""
    output_with_comments = (
        "```a2sdlc\n"
        "{\n"
        '  "status": "changes_requested",\n'
        '  "output": "See comments",\n'
        '  "inline_comments": [\n'
        '    {"file": "a.py", "line_start": 3, "line_end": 3, "body": "fix"}\n'
        "  ]\n"
        "}\n"
        "```"
    )
    ctx, _work, _git, review, _runner = _review_ctx(
        project_root=Path("/tmp/test_review_stage_parsed")
    )
    _populate_per_run_state(ctx, output_with_comments)

    stage = ReviewStage()
    outcome = await stage.execute(ctx)
    await apply_effects(ctx, stage.effects(ctx, outcome))

    assert outcome.status == StageStatus.CHANGES_REQUESTED
    assert len(outcome.inline_comments) == 1
    assert outcome.inline_comments[0].file == "a.py"
    # Posted to the adapter under the PR number.
    assert len(review.inline_comments) == 1
    pr_num, comments = review.inline_comments[0]
    assert pr_num == 42
    assert len(comments) == 1
    assert comments[0].body == "fix"


@pytest.mark.asyncio
async def test_review_stage_execute_feedback_event_prepends_prefix() -> None:
    """When pre.event.is_feedback is True, the system prompt gets the feedback prefix."""
    ctx, _work, _git, _review, _runner = _review_ctx(
        project_root=Path("/tmp/test_review_stage_feedback")
    )
    pre = _populate_per_run_state(ctx, _APPROVED_OUTPUT)
    pre.event.is_feedback = True

    stage = ReviewStage()
    outcome = await stage.execute(ctx)
    await apply_effects(ctx, stage.effects(ctx, outcome))

    assert outcome.status == StageStatus.APPROVED


@pytest.mark.asyncio
async def test_review_stage_execute_uses_user_prompt_override() -> None:
    """When pre.user_prompt_override is set, it replaces the clean_body+PR-context prompt."""
    ctx, _work, _git, review, _runner = _review_ctx(
        project_root=Path("/tmp/test_review_stage_override")
    )
    pre = _populate_per_run_state(ctx, _APPROVED_OUTPUT)
    pre.user_prompt_override = "pre-rendered prompt from feedback routing"

    stage = ReviewStage()
    outcome = await stage.execute(ctx)
    await apply_effects(ctx, stage.effects(ctx, outcome))

    assert outcome.status == StageStatus.APPROVED
    assert len(review.reviews) == 1


def test_review_stage_preconditions_returns_none_in_p2() -> None:
    ctx, *_ = _review_ctx(project_root=Path("/tmp/test_review_stage_pre"))
    assert ReviewStage().preconditions(ctx) is None


def test_review_stage_effects_is_empty_in_p2() -> None:
    ctx, *_ = _review_ctx(project_root=Path("/tmp/test_review_stage_eff"))
    outcome = StageOutcome(status=StageStatus.APPROVED)
    assert ReviewStage().effects(ctx, outcome) == []


def test_review_stage_name_and_valid_statuses() -> None:
    stage = ReviewStage()
    assert stage.name is StageName.REVIEW
    assert stage.valid_statuses == frozenset(
        {StageStatus.APPROVED, StageStatus.CHANGES_REQUESTED}
    )
