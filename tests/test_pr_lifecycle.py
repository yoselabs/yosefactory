"""Tests for PRLifecycle — draft PR creation, updates, merge gate."""

from __future__ import annotations

from a2sdlc.adapters.review import Approval, ReviewComment
from a2sdlc.pr_lifecycle import PRLifecycle
from tests.fakes import FakeReviewAdapter


# -- create_draft -------------------------------------------------------


def test_create_draft_returns_pr_number() -> None:
    adapter = FakeReviewAdapter()
    lc = PRLifecycle(adapter)
    pr = lc.create_draft("agent/35", "main", "35")
    assert pr == 1


def test_create_draft_passes_correct_args() -> None:
    adapter = FakeReviewAdapter()
    lc = PRLifecycle(adapter)
    lc.create_draft("agent/35", "main", "35")
    assert len(adapter.created_prs) == 1
    branch, base, title, key = adapter.created_prs[0]
    assert branch == "agent/35"
    assert base == "main"
    assert "35" in title
    assert key == "35"


# -- check_human_approval ---------------------------------------------


def test_human_approval_true_when_non_bot() -> None:
    adapter = FakeReviewAdapter(approvals=[Approval(user="alice", is_bot=False)])
    lc = PRLifecycle(adapter)
    assert lc.check_human_approval(1) is True


def test_human_approval_false_when_only_bots() -> None:
    adapter = FakeReviewAdapter(approvals=[Approval(user="a2sdlc[bot]", is_bot=True)])
    lc = PRLifecycle(adapter)
    assert lc.check_human_approval(1) is False


def test_human_approval_false_when_no_approvals() -> None:
    adapter = FakeReviewAdapter()
    lc = PRLifecycle(adapter)
    assert lc.check_human_approval(1) is False


# -- merge -------------------------------------------------------------


def test_merge_calls_mark_ready_then_merge() -> None:
    adapter = FakeReviewAdapter()
    lc = PRLifecycle(adapter)
    lc.merge(8)
    assert adapter.ready_prs == [8]
    assert len(adapter.merged_prs) == 1
    pr_num, method = adapter.merged_prs[0]
    assert pr_num == 8
    assert method == "squash"


def test_merge_custom_method() -> None:
    adapter = FakeReviewAdapter()
    lc = PRLifecycle(adapter)
    lc.merge(5, method="merge")
    _, method = adapter.merged_prs[0]
    assert method == "merge"


# -- post_review -------------------------------------------------------


def test_post_review_forwards() -> None:
    adapter = FakeReviewAdapter()
    lc = PRLifecycle(adapter)
    lc.post_review(1, "LGTM", "APPROVE")
    assert adapter.reviews == [(1, "LGTM", "APPROVE")]


# -- read_context ------------------------------------------------------


def test_read_context_combines_diff_and_comments() -> None:
    adapter = FakeReviewAdapter(
        pr_diff="diff --git a/file.py",
        pr_comments=[
            ReviewComment(author="alice", body="Looks good", created_at="2026-04-12"),
        ],
    )
    lc = PRLifecycle(adapter)
    ctx = lc.read_context(1)
    assert "## PR Diff" in ctx
    assert "diff --git a/file.py" in ctx
    assert "## Review Comments" in ctx
    assert "alice" in ctx
    assert "Looks good" in ctx


def test_read_context_no_comments() -> None:
    adapter = FakeReviewAdapter(pr_diff="diff content")
    lc = PRLifecycle(adapter)
    ctx = lc.read_context(1)
    assert "## PR Diff" in ctx
    assert "diff content" in ctx
    assert "## Review Comments" in ctx
