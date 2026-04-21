"""Tests for GitHubReviewAdapter — PR lifecycle, reviews, approvals."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from a2sdlc.adapters.review.github import GitHubReviewAdapter
from a2sdlc.adapters.review import Approval, ReviewComment


def _make_adapter() -> GitHubReviewAdapter:
    """Create a GitHubReviewAdapter with a mock repo."""
    return GitHubReviewAdapter(repo=MagicMock())


@pytest.mark.unit
class TestCreateDraftPr:
    def test_creates_pr_and_returns_number(self) -> None:
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_repo.owner.login = "yoselabs"
        mock_repo.get_pulls.return_value = iter([])
        mock_pr = MagicMock()
        mock_pr.number = 7
        mock_repo.create_pull.return_value = mock_pr
        adapter._repo = mock_repo

        result = adapter.create_draft_pr("agent/15", "main", "feat: X", "15")

        assert result == 7
        mock_repo.get_pulls.assert_called_once_with(
            state="open", head="yoselabs:agent/15"
        )
        mock_repo.create_pull.assert_called_once_with(
            title="feat: X",
            body="Closes #15",
            head="agent/15",
            base="main",
            draft=True,
        )

    def test_reuses_existing_open_pr_for_branch(self) -> None:
        """If an open PR already exists for the branch, return its number instead of 422ing."""
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_repo.owner.login = "yoselabs"
        existing = MagicMock()
        existing.number = 42
        mock_repo.get_pulls.return_value = iter([existing])
        adapter._repo = mock_repo

        result = adapter.create_draft_pr("agent/15", "main", "feat: X", "15")

        assert result == 42
        mock_repo.create_pull.assert_not_called()


@pytest.mark.unit
class TestUpdatePr:
    def test_updates_title_and_body_with_closing_ref(self) -> None:
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        adapter.update_pr(7, "new title", "new body", "15")

        mock_pr.edit.assert_called_once_with(
            title="new title", body="new body\n\nCloses #15"
        )


@pytest.mark.unit
class TestMarkPrReady:
    def test_patches_draft_false(self) -> None:
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_repo.url = "https://api.github.com/repos/owner/repo"
        adapter._repo = mock_repo

        adapter.mark_pr_ready(7)

        mock_repo._requester.requestJsonAndCheck.assert_called_once_with(
            "PATCH",
            "https://api.github.com/repos/owner/repo/pulls/7",
            input={"draft": False},
        )


@pytest.mark.unit
class TestGetApprovals:
    def test_returns_approvals_with_bot_flag(self) -> None:
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        human_review = MagicMock()
        human_review.state = "APPROVED"
        human_review.user = MagicMock()
        human_review.user.login = "alice"
        human_review.user.type = "User"
        bot_review = MagicMock()
        bot_review.state = "APPROVED"
        bot_review.user = MagicMock()
        bot_review.user.login = "dependabot"
        bot_review.user.type = "Bot"
        comment_review = MagicMock()
        comment_review.state = "COMMENTED"
        mock_pr.get_reviews.return_value = [human_review, bot_review, comment_review]
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        result = adapter.get_approvals(7)

        assert len(result) == 2
        assert result[0] == Approval(user="alice", is_bot=False)
        assert result[1] == Approval(user="dependabot", is_bot=True)

    def test_no_approvals_returns_empty(self) -> None:
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.get_reviews.return_value = []
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        assert adapter.get_approvals(7) == []


@pytest.mark.unit
class TestPostReview:
    def test_approve(self) -> None:
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        adapter.post_review(42, "LGTM", "APPROVE")

        mock_repo.get_pull.assert_called_once_with(42)
        mock_pr.create_review.assert_called_once_with(body="LGTM", event="APPROVE")

    def test_fallback_to_comment_on_failure(self) -> None:
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.create_review.side_effect = RuntimeError("cannot approve own PR")
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        adapter.post_review(42, "LGTM", "APPROVE")

        mock_pr.create_issue_comment.assert_called_once()
        body = mock_pr.create_issue_comment.call_args[0][0]
        assert "APPROVE" in body
        assert "LGTM" in body


@pytest.mark.unit
class TestReadPrDiff:
    def test_combines_file_patches(self) -> None:
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        f1 = MagicMock()
        f1.filename = "src/app.py"
        f1.patch = "+print('hello')"
        f2 = MagicMock()
        f2.filename = "src/lib.py"
        f2.patch = None
        mock_pr.get_files.return_value = [f1, f2]
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        result = adapter.read_pr_diff(7)

        assert "--- src/app.py" in result
        assert "+print('hello')" in result
        assert "--- src/lib.py" in result


@pytest.mark.unit
class TestReadPrComments:
    def test_returns_review_comments(self) -> None:
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        c1 = MagicMock()
        c1.user = MagicMock()
        c1.user.login = "alice"
        c1.body = "nice work"
        c1.created_at = MagicMock()
        c1.created_at.isoformat.return_value = "2026-04-12T10:00:00Z"
        mock_pr.get_issue_comments.return_value = [c1]
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        result = adapter.read_pr_comments(7)

        assert len(result) == 1
        assert result[0] == ReviewComment(
            author="alice", body="nice work", created_at="2026-04-12T10:00:00Z"
        )

    def test_empty_comments(self) -> None:
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.get_issue_comments.return_value = []
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        assert adapter.read_pr_comments(7) == []


@pytest.mark.unit
class TestMergePr:
    def test_squash_merge(self) -> None:
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        adapter.merge_pr(42)

        mock_repo.get_pull.assert_called_once_with(42)
        mock_pr.merge.assert_called_once_with(merge_method="squash")

    def test_merge_method_passed(self) -> None:
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        adapter.merge_pr(42, method="merge")

        mock_pr.merge.assert_called_once_with(merge_method="merge")


# ── Feedback: find_last_handover ────────────────────────────────────


@pytest.mark.unit
class TestReviewFindLastHandover:
    def test_returns_most_recent_handover(self) -> None:
        from datetime import datetime, timezone

        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_issue = MagicMock()

        c1 = MagicMock()
        c1.body = "a2sdlc:review\nhandover body 1"
        c1.id = 300
        c1.created_at = datetime(2026, 4, 10, tzinfo=timezone.utc)

        c2 = MagicMock()
        c2.body = "a2sdlc:review\nhandover body 2"
        c2.id = 301
        c2.created_at = datetime(2026, 4, 12, tzinfo=timezone.utc)

        mock_issue.get_comments.return_value = [c1, c2]
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        result = adapter.find_last_handover(42)

        assert result is not None
        assert result.run_id == "301"
        assert result.location == "pr"

    def test_returns_none_when_no_handovers(self) -> None:
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_issue = MagicMock()

        c1 = MagicMock()
        c1.body = "normal comment"
        c1.id = 300
        c1.created_at = MagicMock()

        mock_issue.get_comments.return_value = [c1]
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        assert adapter.find_last_handover(42) is None


# ── Feedback: collect_pr_feedback ───────────────────────────────────


@pytest.mark.unit
class TestCollectPrFeedback:
    def test_returns_reviews_and_inline_comments(self) -> None:
        from datetime import datetime, timezone

        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()

        since = datetime(2026, 4, 10, tzinfo=timezone.utc)

        # A human review
        review = MagicMock()
        review.id = 400
        review.body = "Needs changes"
        review.submitted_at = datetime(2026, 4, 11, tzinfo=timezone.utc)
        review.user = MagicMock()
        review.user.login = "alice"
        review.user.type = "User"

        mock_pr.get_reviews.return_value = [review]

        # An inline comment
        inline = MagicMock()
        inline.id = 500
        inline.body = "Fix this line"
        inline.created_at = datetime(2026, 4, 11, tzinfo=timezone.utc)
        inline.user = MagicMock()
        inline.user.login = "bob"
        inline.user.type = "User"
        inline.path = "src/app.py"
        inline.line = 42

        mock_pr.get_review_comments.return_value = [inline]
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        result = adapter.collect_pr_feedback(7, since)

        assert len(result) == 2
        # Review
        assert result[0].id == "400"
        assert result[0].source == "pr_review"
        assert result[0].author == "alice"
        # Inline
        assert result[1].id == "500"
        assert result[1].source == "pr_inline"
        assert result[1].file_path == "src/app.py"
        assert result[1].line_range == (42, 42)

    def test_excludes_bot_reviews(self) -> None:
        from datetime import datetime, timezone

        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()

        since = datetime(2026, 4, 10, tzinfo=timezone.utc)

        bot_review = MagicMock()
        bot_review.id = 400
        bot_review.body = "Auto-approved"
        bot_review.submitted_at = datetime(2026, 4, 11, tzinfo=timezone.utc)
        bot_review.user = MagicMock()
        bot_review.user.login = "dependabot"
        bot_review.user.type = "Bot"

        mock_pr.get_reviews.return_value = [bot_review]
        mock_pr.get_review_comments.return_value = []
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        result = adapter.collect_pr_feedback(7, since)

        assert result == []

    def test_excludes_reviews_before_since(self) -> None:
        from datetime import datetime, timezone

        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()

        since = datetime(2026, 4, 10, tzinfo=timezone.utc)

        old_review = MagicMock()
        old_review.id = 400
        old_review.body = "Old review"
        old_review.submitted_at = datetime(2026, 4, 9, tzinfo=timezone.utc)
        old_review.user = MagicMock()
        old_review.user.login = "alice"
        old_review.user.type = "User"

        mock_pr.get_reviews.return_value = [old_review]
        mock_pr.get_review_comments.return_value = []
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        result = adapter.collect_pr_feedback(7, since)

        assert result == []

    def test_excludes_bot_inline_comments(self) -> None:
        from datetime import datetime, timezone

        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()

        since = datetime(2026, 4, 10, tzinfo=timezone.utc)

        mock_pr.get_reviews.return_value = []

        bot_inline = MagicMock()
        bot_inline.id = 500
        bot_inline.body = "Bot comment"
        bot_inline.created_at = datetime(2026, 4, 11, tzinfo=timezone.utc)
        bot_inline.user = MagicMock()
        bot_inline.user.login = "codecov"
        bot_inline.user.type = "Bot"
        bot_inline.path = "src/app.py"
        bot_inline.line = 10

        mock_pr.get_review_comments.return_value = [bot_inline]
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        result = adapter.collect_pr_feedback(7, since)

        assert result == []

    def test_excludes_reviews_without_body(self) -> None:
        from datetime import datetime, timezone

        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()

        since = datetime(2026, 4, 10, tzinfo=timezone.utc)

        empty_review = MagicMock()
        empty_review.id = 400
        empty_review.body = ""
        empty_review.submitted_at = datetime(2026, 4, 11, tzinfo=timezone.utc)
        empty_review.user = MagicMock()
        empty_review.user.login = "alice"
        empty_review.user.type = "User"

        mock_pr.get_reviews.return_value = [empty_review]
        mock_pr.get_review_comments.return_value = []
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        result = adapter.collect_pr_feedback(7, since)

        assert result == []
