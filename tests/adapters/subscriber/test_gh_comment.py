"""GhCommentSubscriber — edits the issue/PR comment with throttled status."""

from __future__ import annotations

import pytest

from a2sdlc.adapters.subscriber.gh_comment import GhCommentSubscriber
from a2sdlc.domain.models import StageName
from a2sdlc.domain.progress import (
    Metrics,
    Milestone,
    ProgressState,
    StageEnd,
    StageStart,
)


class _FakeComment:
    """Mirrors the real ``CommentManager`` surface (``update``/``finalize`` only)
    so signature drift between subscriber and manager surfaces in tests."""

    def __init__(self) -> None:
        self.updates: list[str] = []
        self.finalized: str | None = None

    def update(self, text: str) -> None:
        self.updates.append(text)

    def finalize(self, text: str) -> None:
        self.finalized = text


def _state() -> ProgressState:
    return ProgressState(project_root="/tmp")


@pytest.mark.asyncio
async def test_first_metrics_event_updates_comment() -> None:
    state = _state()
    comment = _FakeComment()
    sub = GhCommentSubscriber(comment, state, throttle_seconds=0.0)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid", started_at=0.0))
    await sub.handle(Metrics(1, 2, 0.05, 1, 0.0))
    assert len(comment.updates) == 1


@pytest.mark.asyncio
async def test_metrics_within_throttle_window_drops_update() -> None:
    state = _state()
    comment = _FakeComment()
    sub = GhCommentSubscriber(comment, state, throttle_seconds=10.0)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid", started_at=0.0))
    await sub.handle(Metrics(1, 2, 0.05, 1, 0.0))
    await sub.handle(Metrics(2, 3, 0.10, 2, 1.0))
    assert len(comment.updates) == 1


@pytest.mark.asyncio
async def test_milestone_event_does_not_call_unsupported_append() -> None:
    """Milestones land in the comment via the next throttled Metrics tick
    (format_progress already includes the milestones list). The subscriber
    must NOT call any method beyond update/finalize on the comment handle —
    CommentManager has no append/post/etc. and silently failing here would
    disable the subscriber for the rest of the stage."""
    state = _state()
    comment = _FakeComment()
    sub = GhCommentSubscriber(comment, state, throttle_seconds=10.0)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid", started_at=0.0))
    await sub.handle(Milestone(timestamp=0.5, label="brainstorming invoked"))
    await sub.handle(Milestone(timestamp=1.0, label="spec approved"))
    # No update/finalize triggered by Milestone.
    assert comment.updates == []
    assert comment.finalized is None


@pytest.mark.asyncio
async def test_stage_end_finalizes_with_success_marker() -> None:
    state = _state()
    comment = _FakeComment()
    sub = GhCommentSubscriber(comment, state, throttle_seconds=0.0)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid", started_at=0.0))
    final = Metrics(
        input_tokens=10,
        output_tokens=20,
        total_cost_usd=0.42,
        num_turns=5,
        elapsed=30.0,
    )
    await sub.handle(
        StageEnd(stage=StageName.SPEC, success=True, error=None, final_metrics=final)
    )
    assert comment.finalized is not None
    assert "spec done" in comment.finalized
    assert "$0.42" in comment.finalized
    assert "5 turns" in comment.finalized
    assert "\u2705" in comment.finalized


@pytest.mark.asyncio
async def test_subscriber_uses_only_real_comment_manager_methods() -> None:
    """Regression: subscriber must call ONLY methods that CommentManager
    actually exposes (start/update/finalize). A previous version called
    .append() — silently disabled the subscriber for the rest of the
    stage when the AttributeError got swallowed by ProgressState._emit's
    broad exception handler."""
    from a2sdlc.lifecycle.comment import CommentManager
    from tests.fakes import FakeWorkAdapter
    from a2sdlc.domain.pipeline_event import PipelineEvent

    work = FakeWorkAdapter(
        event=PipelineEvent(key="42", trigger_stage=StageName.SPEC),
        ticket_body="x",
    )
    cm = CommentManager(work, "42")
    cm.start("spec")
    state = _state()
    sub = GhCommentSubscriber(cm, state, throttle_seconds=0.0)

    # Drive every event type the subscriber handles — none should raise.
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid", started_at=0.0))
    await sub.handle(Metrics(1, 2, 0.05, 1, 0.0))
    await sub.handle(Milestone(timestamp=0.5, label="brainstorming invoked"))
    final = Metrics(0, 0, 0.0, 0, 0.0)
    await sub.handle(
        StageEnd(stage=StageName.SPEC, success=True, error=None, final_metrics=final)
    )


@pytest.mark.asyncio
async def test_stage_end_finalizes_with_failure_marker() -> None:
    state = _state()
    comment = _FakeComment()
    sub = GhCommentSubscriber(comment, state, throttle_seconds=0.0)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid", started_at=0.0))
    final = Metrics(0, 0, 0.0, 0, 0.0)
    await sub.handle(
        StageEnd(stage=StageName.SPEC, success=False, error="boom", final_metrics=final)
    )
    assert comment.finalized is not None
    assert "\u274c" in comment.finalized
