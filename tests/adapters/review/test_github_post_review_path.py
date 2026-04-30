"""Path-return + fallback-dedupe coverage for GitHubReviewAdapter.post_review.

Extracted from test_github.py to keep that file under the 500-line cap.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from a2sdlc.adapters.review.github import GitHubReviewAdapter


def _make_adapter() -> GitHubReviewAdapter:
    return GitHubReviewAdapter(repo=MagicMock())


@pytest.mark.unit
class TestPostReviewPath:
    def test_post_review_returns_path(self) -> None:
        """post_review returns a Path that mirrors the review body."""
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        p = adapter.post_review(pr_number=1, body="hi", verdict="approved")

        assert isinstance(p, Path)
        assert p.exists()
        text = p.read_text()
        assert "approved" in text
        assert "hi" in text

    def test_returns_path_on_self_approval_skip(self) -> None:
        """Self-approval 422 still produces a side-staging path."""
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.create_review.side_effect = RuntimeError(
            "Can not approve your own pull request"
        )
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        p = adapter.post_review(99, "LGTM", "APPROVE")

        assert isinstance(p, Path)
        assert p.exists()
        mock_pr.create_issue_comment.assert_not_called()

    def test_fallback_dedupe_skips_when_marker_already_present(self) -> None:
        """Retries must not stack duplicate fallback comments."""
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.create_review.side_effect = RuntimeError("boom")
        existing = MagicMock()
        existing.body = "**Review: APPROVE**\n\nLGTM"
        mock_pr.get_issue_comments.return_value = [existing]
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        adapter.post_review(42, "LGTM", "APPROVE")

        mock_pr.create_issue_comment.assert_not_called()

    def test_fallback_when_get_issue_comments_raises(self) -> None:
        """If listing existing comments fails, still post the fallback comment."""
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.create_review.side_effect = RuntimeError("boom")
        mock_pr.get_issue_comments.side_effect = RuntimeError("rate limit")
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        adapter.post_review(42, "LGTM", "APPROVE")

        mock_pr.create_issue_comment.assert_called_once()
