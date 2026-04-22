"""Recorded integration tests for GitHubReviewAdapter.

Read-only mirror of test_github_work.py for the PR surface. See that
module's docstring for the recording/replay workflow.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from a2sdlc.adapters.review.github import GitHubReviewAdapter
from github import Github


# Stable merged PR in iorlas/a2sdlc-smoke, same cohort as KNOWN_TICKET
# (smoke #12 merged PR). A merged PR guarantees the branch is retained
# as refs/heads/agent/12 unless someone deleted it — re-record if so.
KNOWN_PR = 13  # merge PR created by the engine for ticket #12; adjust on re-record


pytestmark = [pytest.mark.integration, pytest.mark.vcr]


def _adapter(token: str, repo_name: str) -> GitHubReviewAdapter:
    # ReviewAdapter doesn't have a from_token factory yet; construct
    # PyGithub directly. Same auth path as WorkAdapter.from_token — the
    # Github(token) constructor is shared.
    gh = Github(token)
    return GitHubReviewAdapter(gh.get_repo(repo_name))


def test_get_approvals_shape(gh_token: str, smoke_repo: str) -> None:
    adapter = _adapter(gh_token, smoke_repo)
    approvals = adapter.get_approvals(KNOWN_PR)
    assert isinstance(approvals, list)
    for a in approvals:
        assert isinstance(a.user, str)
        assert isinstance(a.is_bot, bool)


def test_read_pr_diff_nonempty(gh_token: str, smoke_repo: str) -> None:
    adapter = _adapter(gh_token, smoke_repo)
    diff = adapter.read_pr_diff(KNOWN_PR)
    assert isinstance(diff, str)
    # A merged PR that changed at least one file will produce a patch;
    # if this asserts empty, re-record picked an empty PR.
    assert diff, "expected a non-empty diff on the recorded merged PR"


def test_read_pr_comments_shape(gh_token: str, smoke_repo: str) -> None:
    adapter = _adapter(gh_token, smoke_repo)
    comments = adapter.read_pr_comments(KNOWN_PR)
    assert isinstance(comments, list)
    for c in comments:
        assert isinstance(c.author, str)
        assert isinstance(c.body, str)


def test_collect_pr_feedback_accepts_since(gh_token: str, smoke_repo: str) -> None:
    adapter = _adapter(gh_token, smoke_repo)
    since = datetime(2020, 1, 1, tzinfo=UTC)
    items = adapter.collect_pr_feedback(KNOWN_PR, since)
    assert isinstance(items, list)


def test_find_last_handover_returns_none_or_handover(
    gh_token: str, smoke_repo: str
) -> None:
    adapter = _adapter(gh_token, smoke_repo)
    result = adapter.find_last_handover(KNOWN_PR)
    # Shape-only: either None (no handover on this PR) or a parsed
    # HandoverComment. The key assertion is that the comment-scan path
    # doesn't blow up under real response data.
    assert result is None or hasattr(result, "created_at")
