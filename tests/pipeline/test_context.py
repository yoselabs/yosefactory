"""Tests for context assembly — the uniform handover-based algorithm."""

from datetime import datetime, timezone

from a2sdlc.pipeline.context import assemble_context, pick_handover
from a2sdlc.domain.handover import FeedbackItem, HandoverComment
from a2sdlc.domain.models import StageName


def _dt(day: int) -> datetime:
    return datetime(2026, 4, day, tzinfo=timezone.utc)


def test_first_run_no_handover():
    """First run: no handover exists, ticket body is the only context."""
    result = assemble_context(
        ticket_body="Add drag and drop support",
        issue_handover=None,
        pr_handover=None,
        issue_feedback=[],
        pr_feedback=[],
        pr_diff=None,
    )
    assert result.user_prompt == "Add drag and drop support"
    assert result.feedback == []
    assert result.current_stage is None
    assert result.is_first_run is True


def test_with_handover_and_feedback():
    """After a stage, handover body + feedback are assembled."""
    handover = HandoverComment(
        stage=StageName.IMPLEMENT,
        run_id="r1",
        body="## Implementation Complete\nAdded drag and drop.",
        created_at=_dt(10),
        location="issue",
    )
    feedback = [
        FeedbackItem(
            id="f1",
            author="jane",
            author_type="human",
            source="issue_comment",
            body="@a2sdlc drag and drop broken on mobile",
            created_at=_dt(11),
        )
    ]
    result = assemble_context(
        ticket_body="Add drag and drop support",
        issue_handover=handover,
        pr_handover=None,
        issue_feedback=feedback,
        pr_feedback=[],
        pr_diff=None,
    )
    assert "Add drag and drop support" in result.user_prompt
    assert "Implementation Complete" in result.user_prompt
    assert "drag and drop broken on mobile" in result.user_prompt
    assert result.current_stage == StageName.IMPLEMENT
    assert result.is_first_run is False
    assert len(result.feedback) == 1


def test_pr_handover_preferred_when_later_stage():
    """If PR has a REVIEW handover and issue has IMPLEMENT, prefer REVIEW."""
    issue_ho = HandoverComment(
        stage=StageName.IMPLEMENT,
        run_id="r1",
        body="impl done",
        created_at=_dt(10),
        location="issue",
    )
    pr_ho = HandoverComment(
        stage=StageName.REVIEW,
        run_id="r2",
        body="review done",
        created_at=_dt(10),
        location="pr",
    )
    result = assemble_context(
        ticket_body="ticket",
        issue_handover=issue_ho,
        pr_handover=pr_ho,
        issue_feedback=[],
        pr_feedback=[],
        pr_diff=None,
    )
    assert result.current_stage == StageName.REVIEW
    assert "review done" in result.user_prompt


def test_pr_diff_included():
    """PR diff is appended when available."""
    result = assemble_context(
        ticket_body="ticket",
        issue_handover=None,
        pr_handover=None,
        issue_feedback=[],
        pr_feedback=[],
        pr_diff="--- a/file.py\n+++ b/file.py\n+ new line",
    )
    assert "Current PR Diff" in result.user_prompt
    assert "new line" in result.user_prompt


def test_feedback_sorted_by_time():
    """Feedback items are sorted by created_at."""
    f1 = FeedbackItem(
        id="1",
        author="a",
        author_type="human",
        source="issue_comment",
        body="first",
        created_at=_dt(12),
    )
    f2 = FeedbackItem(
        id="2",
        author="b",
        author_type="human",
        source="pr_review",
        body="second",
        created_at=_dt(11),
    )
    result = assemble_context(
        ticket_body="ticket",
        issue_handover=None,
        pr_handover=None,
        issue_feedback=[f1],
        pr_feedback=[f2],
        pr_diff=None,
    )
    # f2 (day 11) should appear before f1 (day 12) in the prompt
    idx_second = result.user_prompt.index("second")
    idx_first = result.user_prompt.index("first")
    assert idx_second < idx_first


def test_inline_feedback_includes_file_location():
    """Inline feedback shows file path and line range."""
    fb = FeedbackItem(
        id="1",
        author="jane",
        author_type="human",
        source="pr_inline",
        body="Fix this null check",
        file_path="src/main.py",
        line_range=(45, 52),
        created_at=_dt(10),
    )
    result = assemble_context(
        ticket_body="ticket",
        issue_handover=None,
        pr_handover=None,
        issue_feedback=[],
        pr_feedback=[fb],
        pr_diff=None,
    )
    assert "`src/main.py`" in result.user_prompt
    assert "lines 45-52" in result.user_prompt


def testpick_handover_issue_newer():
    """pick_handover prefers the more recent handover."""
    issue = HandoverComment(
        stage=StageName.IMPLEMENT,
        run_id="r1",
        body="",
        created_at=_dt(12),
        location="issue",
    )
    pr = HandoverComment(
        stage=StageName.REVIEW, run_id="r2", body="", created_at=_dt(10), location="pr"
    )
    assert pick_handover(issue, pr) == issue


def testpick_handover_none_handling():
    """pick_handover handles None inputs."""
    ho = HandoverComment(
        stage=StageName.SPEC, run_id="r1", body="", created_at=_dt(10), location="issue"
    )
    assert pick_handover(ho, None) == ho
    assert pick_handover(None, ho) == ho
    assert pick_handover(None, None) is None
