"""L1 tests for the effects interpreter — one test per V1.0 arm.

Uses the fake adapters from ``tests/fakes.py`` so each arm's adapter
call can be asserted on the recorded call list. Standalone-invocability
aligned: we build a ``RunContext`` with fakes, populate the
per-run state fields, and call ``apply`` directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from a2sdlc.domain.effects import (
    AwaitHumanDecision,
    CleanupBase,
    CommentFinalize,
    CommitAndPush,
    CreateDraftPR,
    LogMetric,
    MarkBlocked,
    MarkDone,
    MarkNeedsInput,
    MergePR,
    PostInlineReview,
    PostReview,
    SetCurrentStage,
    StateWrite,
)
from a2sdlc.domain.models import StageName, TicketState
from a2sdlc.domain.pipeline_event import PipelineEvent
from a2sdlc.domain.stage_outcome import InlineComment
from a2sdlc.lifecycle.comment import CommentManager
from a2sdlc.lifecycle.pr import PRLifecycle
from a2sdlc.effects.apply import apply
from tests.fakes import make_dispatch_context, populate_run_intent


def _ctx_with_run_state(stage: StageName = StageName.SPEC) -> Any:
    event = PipelineEvent(key="42", trigger_stage=stage)
    ctx, work, git, review, _runner = make_dispatch_context(
        event=event,
        project_root=Path(f"/tmp/test_effects_{stage.value}"),
    )
    intent = populate_run_intent(ctx)
    ctx.intent = intent
    ctx.pr_lifecycle = PRLifecycle(ctx.review)
    ctx.comment = CommentManager(ctx.work, intent.event.key)
    ctx.comment.start(intent.target_stage.value)
    ctx.pr_number = 7
    ctx.run = MagicMock(name="RunHandle")
    return ctx, work, git, review


@pytest.mark.asyncio
async def test_apply_empty_list_is_noop() -> None:
    ctx, *_ = _ctx_with_run_state()
    await apply(ctx, [])  # no raise


@pytest.mark.asyncio
async def test_mark_blocked_calls_adapter_with_key() -> None:
    ctx, work, *_ = _ctx_with_run_state()
    await apply(ctx, [MarkBlocked(reason="timeout")])
    assert work.blocked == [("42", "timeout")]


@pytest.mark.asyncio
async def test_mark_done_uses_pre_event_key() -> None:
    ctx, work, *_ = _ctx_with_run_state()
    await apply(ctx, [MarkDone()])
    assert ("42", "stage:done") in work.label_history


@pytest.mark.asyncio
async def test_mark_needs_input_calls_adapter() -> None:
    ctx, work, *_ = _ctx_with_run_state()
    await apply(ctx, [MarkNeedsInput()])
    assert work.needs_input == ["42"]


@pytest.mark.asyncio
async def test_await_human_decision_no_adapter_side_effect(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """V1.0 interpreter arm: structured log, no adapter side effect."""
    import logging

    ctx, work, *_ = _ctx_with_run_state()
    ctx.logger = logging.getLogger("test.await_human")
    ctx.logger.setLevel(logging.INFO)

    with caplog.at_level(logging.INFO, logger="test.await_human"):
        await apply(
            ctx,
            [AwaitHumanDecision(kind="approval", reason="waiting_for_approval")],
        )

    # No adapter mutation — this is a dispatch-level signal effect.
    assert work.blocked == []
    assert work.label_history == []
    # Structured log fired with kind/reason fields.
    matching = [
        r
        for r in caplog.records
        if r.message == "dispatch.await_human"
        and getattr(r, "kind", None) == "approval"
        and getattr(r, "reason", None) == "waiting_for_approval"
    ]
    assert len(matching) == 1


@pytest.mark.asyncio
async def test_set_current_stage_records_transition() -> None:
    ctx, work, *_ = _ctx_with_run_state()
    await apply(ctx, [SetCurrentStage(stage=StageName.IMPLEMENT)])
    assert ("42", "stage:implement") in work.label_history


@pytest.mark.asyncio
async def test_comment_finalize_flows_to_work_adapter() -> None:
    ctx, work, *_ = _ctx_with_run_state()
    await apply(ctx, [CommentFinalize(body="final text")])
    assert len(work.finalized_comments) == 1
    assert work.finalized_comments[0][1] == "final text"


@pytest.mark.asyncio
async def test_post_review_maps_to_review_adapter() -> None:
    ctx, _work, _git, review = _ctx_with_run_state()
    await apply(ctx, [PostReview(pr_number=7, verdict="APPROVE", body="LGTM")])
    assert review.reviews == [(7, "LGTM", "APPROVE")]


@pytest.mark.asyncio
async def test_post_inline_review_passes_comments_through() -> None:
    ctx, _work, _git, review = _ctx_with_run_state()
    ic = InlineComment(file="a.py", line_start=1, line_end=1, body="fix")
    await apply(ctx, [PostInlineReview(pr_number=7, comments=[ic])])
    assert len(review.inline_comments) == 1
    pr, comments = review.inline_comments[0]
    assert pr == 7
    assert comments[0].body == "fix"


@pytest.mark.asyncio
async def test_post_inline_review_empty_list_records_empty_call() -> None:
    ctx, _work, _git, review = _ctx_with_run_state()
    await apply(ctx, [PostInlineReview(pr_number=7, comments=[])])
    assert review.inline_comments == [(7, [])]


@pytest.mark.asyncio
async def test_merge_pr_marks_ready_then_merges() -> None:
    ctx, _work, _git, review = _ctx_with_run_state()
    await apply(ctx, [MergePR(pr_number=7)])
    assert review.ready_prs == [7]
    assert review.merged_prs == [(7, "squash")]


@pytest.mark.asyncio
async def test_state_write_passes_to_state_mgr() -> None:
    ctx, _work, git, _review = _ctx_with_run_state()
    ts = TicketState(
        stage=StageName.SPEC,
        branch="agent/42",
        stage_run_id="run-1",
        last_updated="2026-04-25T00:00:00Z",
    )
    await apply(ctx, [StateWrite(state=ts)])
    assert len(git.written_state) == 1


@pytest.mark.asyncio
async def test_commit_and_push_forwards_to_git_adapter() -> None:
    ctx, _work, git, _review = _ctx_with_run_state()
    await apply(
        ctx,
        [CommitAndPush(message="chore: artifacts", paths=("a.json", "docs/"))],
    )
    assert git.commits == [("chore: artifacts", ["a.json", "docs/"])]
    assert len(git.pushes) == 1


@pytest.mark.asyncio
async def test_commit_and_push_swallows_exception_and_logs() -> None:
    """Handler parity — push failures don't abort the effect list."""
    ctx, _work, git, _review = _ctx_with_run_state()

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("push rejected")

    git.push = _boom  # type: ignore[method-assign]

    # Should not raise.
    await apply(ctx, [CommitAndPush(message="m", paths=("p",))])


@pytest.mark.asyncio
async def test_log_metric_calls_run_handle() -> None:
    ctx, *_ = _ctx_with_run_state()
    await apply(ctx, [LogMetric(key="tokens_in", value=1234.0)])
    ctx.run.log_metric.assert_called_once_with("tokens_in", 1234.0)


@pytest.mark.asyncio
async def test_unhandled_arm_raises_not_implemented() -> None:
    """Forward-compat arms without an interpreter branch fail loudly."""
    ctx, *_ = _ctx_with_run_state()
    with pytest.raises(NotImplementedError, match="CreateDraftPR"):
        await apply(ctx, [CreateDraftPR(branch="b", base="main", ticket_key="42")])
    with pytest.raises(NotImplementedError, match="CleanupBase"):
        await apply(ctx, [CleanupBase(base="main")])


@pytest.mark.asyncio
async def test_effects_apply_in_list_order() -> None:
    """Short-circuit on first exception; prior arms must have applied."""
    ctx, work, *_ = _ctx_with_run_state()
    with pytest.raises(NotImplementedError):
        await apply(
            ctx,
            [
                MarkBlocked(reason="first"),
                CleanupBase(base="main"),  # raises
                MarkDone(),  # unreached
            ],
        )
    # The MarkBlocked before the unhandled arm did apply.
    assert work.blocked == [("42", "first")]
    # The MarkDone after the raise did not.
    assert ("42", "stage:done") not in work.label_history
