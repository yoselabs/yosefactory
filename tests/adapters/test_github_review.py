"""Tests for GitHubReviewAdapter — PR lifecycle, reviews, approvals."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from a2sdlc.adapters.github import GitHubReviewAdapter
from a2sdlc.adapters.review import Approval, ReviewComment


def _make_adapter() -> GitHubReviewAdapter:
    """Create a GitHubReviewAdapter with a mock repo."""
    return GitHubReviewAdapter(repo=MagicMock())


@pytest.mark.unit
class TestCreateDraftPr:
    def test_creates_pr_and_returns_number(self) -> None:
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.number = 7
        mock_repo.create_pull.return_value = mock_pr
        adapter._repo = mock_repo

        result = adapter.create_draft_pr("agent/15", "main", "feat: X", "15")

        assert result == 7
        mock_repo.create_pull.assert_called_once_with(
            title="feat: X",
            body="Closes #15",
            head="agent/15",
            base="main",
            draft=True,
        )


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
