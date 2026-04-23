"""Tests for GitHubReviewAdapter.post_inline_comments — N1 inline review."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from a2sdlc.adapters.review.github import GitHubReviewAdapter
from a2sdlc.domain.stage_outcome import InlineComment


def _make_adapter() -> GitHubReviewAdapter:
    return GitHubReviewAdapter(repo=MagicMock())


@pytest.mark.unit
class TestPostInlineComments:
    def test_empty_list_is_noop(self) -> None:
        adapter = _make_adapter()
        mock_repo = MagicMock()
        adapter._repo = mock_repo

        adapter.post_inline_comments(42, [])

        mock_repo.get_pull.assert_not_called()

    def test_posts_single_line_comment(self) -> None:
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        f = MagicMock()
        f.filename = "src/app.py"
        mock_pr.get_files.return_value = [f]
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        adapter.post_inline_comments(
            42,
            [InlineComment(file="src/app.py", line_start=10, line_end=10, body="nit")],
        )

        mock_pr.create_review.assert_called_once()
        kwargs = mock_pr.create_review.call_args.kwargs
        assert kwargs["event"] == "COMMENT"
        assert len(kwargs["comments"]) == 1
        entry = kwargs["comments"][0]
        assert entry["path"] == "src/app.py"
        assert entry["line"] == 10
        assert entry["body"] == "nit"
        assert entry["side"] == "RIGHT"
        assert "start_line" not in entry

    def test_posts_multi_line_comment_includes_start_line(self) -> None:
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        f = MagicMock()
        f.filename = "src/app.py"
        mock_pr.get_files.return_value = [f]
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        adapter.post_inline_comments(
            42,
            [
                InlineComment(
                    file="src/app.py", line_start=10, line_end=14, body="range"
                )
            ],
        )

        entry = mock_pr.create_review.call_args.kwargs["comments"][0]
        assert entry["start_line"] == 10
        assert entry["line"] == 14
        assert entry["start_side"] == "RIGHT"

    def test_drops_comment_not_in_pr_diff(self) -> None:
        """N9 guard: comments against files outside the PR diff are dropped."""
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        f = MagicMock()
        f.filename = "src/app.py"
        mock_pr.get_files.return_value = [f]
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        adapter.post_inline_comments(
            42,
            [
                InlineComment(file="src/app.py", line_start=1, line_end=1, body="ok"),
                InlineComment(
                    file="../../etc/passwd", line_start=1, line_end=1, body="evil"
                ),
            ],
        )

        entries = mock_pr.create_review.call_args.kwargs["comments"]
        assert len(entries) == 1
        assert entries[0]["path"] == "src/app.py"

    def test_all_comments_out_of_diff_skips_review(self) -> None:
        adapter = _make_adapter()
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        f = MagicMock()
        f.filename = "src/app.py"
        mock_pr.get_files.return_value = [f]
        mock_repo.get_pull.return_value = mock_pr
        adapter._repo = mock_repo

        adapter.post_inline_comments(
            42,
            [InlineComment(file="other.py", line_start=1, line_end=1, body="x")],
        )

        mock_pr.create_review.assert_not_called()
