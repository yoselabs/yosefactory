"""Recorded integration tests for GitHubReviewAdapter.

Read-only mirror of test_github_work.py for the PR surface. See that
module's docstring for the recording/replay workflow.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from a2sdlc.adapters.review.github import GitHubReviewAdapter
from a2sdlc.domain.stage_outcome import InlineComment
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


def test_post_inline_comments_against_open_pr(gh_token: str, smoke_repo: str) -> None:
    """L4: record a real `create_review(event=COMMENT, comments=[...])` call.

    Requires a cassette recorded against an OPEN PR in the smoke repo
    (closed/merged PRs reject inline-review submissions with 422). Pick
    a stable open PR in iorlas/a2sdlc-smoke kept around specifically for
    inline-comment recording; adjust the number + file/line on re-record.

    Replay asserts the call doesn't raise — the cassette proves the
    PyGithub + PR-diff auth path works end-to-end under installation
    token auth.
    """
    open_pr = 29  # open draft PR in smoke repo — adjust on re-record
    target_file = (
        "docs/superpowers/specs/2026-04-22-28-input-validation.md"
        # File present in PR #29's diff — adjust on re-record if the PR changes
    )
    adapter = _adapter(gh_token, smoke_repo)
    adapter.post_inline_comments(
        open_pr,
        [
            InlineComment(
                file=target_file,
                line_start=1,
                line_end=1,
                body="a2sdlc cassette probe — safe to ignore",
            )
        ],
    )


def test_find_last_handover_returns_none_or_handover(
    gh_token: str, smoke_repo: str
) -> None:
    adapter = _adapter(gh_token, smoke_repo)
    result = adapter.find_last_handover(KNOWN_PR)
    # Shape-only: either None (no handover on this PR) or a parsed
    # HandoverComment. The key assertion is that the comment-scan path
    # doesn't blow up under real response data.
    assert result is None or hasattr(result, "created_at")
