"""Tests for a2sdlc.adapters.github_code — GitHubCode adapter."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from a2sdlc.adapters.github_code import GitHubCode


@pytest.mark.unit
class TestGitHubCode:
    def setup_method(self) -> None:
        self.adapter = GitHubCode(repo="owner/repo")

    @patch("a2sdlc.adapters.github_code.gh")
    def test_create_pr(self, mock_gh) -> None:
        mock_gh.return_value = "https://github.com/owner/repo/pull/17"
        pr_num = self.adapter.create_pr("Add feature", "Body text", "feat-branch")
        assert pr_num == 17
        mock_gh.assert_called_once()
        args = mock_gh.call_args[0][0]
        assert "pr" in args
        assert "create" in args
        assert "--repo" in args
        assert "owner/repo" in args
        assert "--base" in args
        assert "main" in args
        assert "--head" in args
        assert "feat-branch" in args

    @patch("a2sdlc.adapters.github_code.gh")
    def test_get_pr_context(self, mock_gh) -> None:
        mock_gh.return_value = json.dumps(
            {
                "title": "Fix login bug",
                "body": "Resolved the auth timeout.",
                "files": [
                    {
                        "path": "src/auth.py",
                        "additions": 10,
                        "deletions": 3,
                    },
                    {
                        "path": "tests/test_auth.py",
                        "additions": 25,
                        "deletions": 0,
                    },
                ],
                "comments": [
                    {"author": {"login": "reviewer1"}, "body": "Looks good!"},
                    {"author": {"login": "reviewer2"}, "body": "One nit."},
                ],
            }
        )
        result = self.adapter.get_pr_context(42)
        assert "Fix login bug" in result
        assert "Resolved the auth timeout." in result
        assert "src/auth.py" in result
        assert "+10" in result
        assert "-3" in result
        assert "tests/test_auth.py" in result
        assert "+25" in result
        assert "-0" in result
        assert "reviewer1" in result
        assert "Looks good!" in result
        assert "reviewer2" in result
        assert "One nit." in result
        # Must NOT include diff
        assert "diff" not in result.lower() or "diff" in "Changed files"

    @patch("a2sdlc.adapters.github_code.gh")
    def test_post_review_approve(self, mock_gh) -> None:
        self.adapter.post_review(42, "LGTM", "APPROVE")
        mock_gh.assert_called_once()
        args = mock_gh.call_args[0][0]
        assert "--approve" in args
        assert "--request-changes" not in args

    @patch("a2sdlc.adapters.github_code.gh")
    def test_post_review_request_changes(self, mock_gh) -> None:
        self.adapter.post_review(42, "Please fix X", "REQUEST_CHANGES")
        mock_gh.assert_called_once()
        args = mock_gh.call_args[0][0]
        assert "--request-changes" in args
        assert "--approve" not in args

    @patch("a2sdlc.adapters.github_code.gh")
    def test_merge_pr(self, mock_gh) -> None:
        self.adapter.merge_pr(42)
        mock_gh.assert_called_once()
        args = mock_gh.call_args[0][0]
        assert "--squash" in args
        assert "merge" in args
        assert "42" in [str(a) for a in args]
