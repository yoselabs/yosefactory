"""Behavior tests for local_noop_review adapter."""

import json
import subprocess
from datetime import datetime, timedelta, timezone

from a2sdlc.adapters.local_noop_review import LocalNoopReviewAdapter
from a2sdlc.adapters.review import Approval


def test_create_draft_pr_writes_pr_json(tmp_path):
    """GIVEN a fresh project root
    WHEN create_draft_pr is called
    THEN .a2sdlc/pr.json exists with pr_number=1 and status=draft."""
    (tmp_path / ".a2sdlc").mkdir()
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)

    pr_number = adapter.create_draft_pr(
        branch="a2sdlc/sid", base="main", title="title", ticket_key="sid"
    )

    assert pr_number == 1
    data = json.loads((tmp_path / ".a2sdlc" / "pr.json").read_text())
    assert data["pr_number"] == 1
    assert data["status"] == "draft"
    assert data["title"] == "title"


def test_get_approvals_returns_local_non_bot(tmp_path):
    """Synthetic approval that satisfies check_human_approval."""
    (tmp_path / ".a2sdlc").mkdir()
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    approvals = adapter.get_approvals(1)
    assert approvals == [Approval(user="local", is_bot=False)]


def test_post_review_changes_requested_writes_feedback(tmp_path):
    """changes_requested → feedback.json with consumed=false."""
    (tmp_path / ".a2sdlc").mkdir()
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    adapter.post_review(1, body="Needs work", verdict="changes_requested")

    fb = json.loads((tmp_path / ".a2sdlc" / "feedback.json").read_text())
    assert fb["consumed"] is False
    assert "Needs work" in fb["body"]


def test_post_review_approved_does_not_write_feedback(tmp_path):
    """approved → feedback.json NOT written."""
    (tmp_path / ".a2sdlc").mkdir()
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    adapter.post_review(1, body="LGTM", verdict="approved")
    assert not (tmp_path / ".a2sdlc" / "feedback.json").exists()


def test_collect_pr_feedback_filters_by_since(tmp_path):
    """since > feedback.created_at → empty."""
    (tmp_path / ".a2sdlc").mkdir()
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    adapter.post_review(1, "fix this", "changes_requested")
    since = datetime.now(timezone.utc) + timedelta(hours=1)
    assert adapter.collect_pr_feedback(1, since) == []


def test_collect_pr_feedback_returns_when_since_is_before(tmp_path):
    """since < feedback.created_at → returns one FeedbackItem."""
    (tmp_path / ".a2sdlc").mkdir()
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    adapter.post_review(1, "fix it", "changes_requested")
    items = adapter.collect_pr_feedback(1, datetime.min.replace(tzinfo=timezone.utc))
    assert len(items) == 1
    assert "fix it" in items[0].body


def test_collect_pr_feedback_does_not_consume(tmp_path):
    """Adapter is read-only — runner flips consumed after success."""
    (tmp_path / ".a2sdlc").mkdir()
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    adapter.post_review(1, "fix", "changes_requested")
    adapter.collect_pr_feedback(1, datetime.min.replace(tzinfo=timezone.utc))
    fb = json.loads((tmp_path / ".a2sdlc" / "feedback.json").read_text())
    assert fb["consumed"] is False


def test_collect_pr_feedback_respects_consumed_flag(tmp_path):
    """When feedback is already consumed → empty list."""
    (tmp_path / ".a2sdlc").mkdir()
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    adapter.post_review(1, "fix", "changes_requested")
    adapter.mark_feedback_consumed()
    items = adapter.collect_pr_feedback(1, datetime.min.replace(tzinfo=timezone.utc))
    assert items == []


def test_merge_pr_updates_status(tmp_path):
    """merge_pr → pr.json.status = 'merged'."""
    (tmp_path / ".a2sdlc").mkdir()
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    adapter.merge_pr(1)
    data = json.loads((tmp_path / ".a2sdlc" / "pr.json").read_text())
    assert data["status"] == "merged"


def test_mark_pr_ready_updates_status(tmp_path):
    """mark_pr_ready → pr.json.status = 'ready'."""
    (tmp_path / ".a2sdlc").mkdir()
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    adapter.mark_pr_ready(1)
    data = json.loads((tmp_path / ".a2sdlc" / "pr.json").read_text())
    assert data["status"] == "ready"


def test_find_last_handover_returns_none(tmp_path):
    """PR-side handover is not used locally — always None."""
    (tmp_path / ".a2sdlc").mkdir()
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    assert adapter.find_last_handover(1) is None


def test_read_pr_diff_returns_string(tmp_path):
    """read_pr_diff shells out to `git diff base..HEAD` — returns whatever git outputs."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("init")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    (tmp_path / ".a2sdlc").mkdir()

    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    diff = adapter.read_pr_diff(1)
    assert isinstance(diff, str)


def test_update_pr_updates_fields(tmp_path):
    """update_pr edits title/body/ticket_key in pr.json."""
    (tmp_path / ".a2sdlc").mkdir()
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "old", "sid")
    adapter.update_pr(1, title="new", body="new body", ticket_key="sid")
    data = json.loads((tmp_path / ".a2sdlc" / "pr.json").read_text())
    assert data["title"] == "new"
    assert data["body"] == "new body"


def test_read_pr_comments_maps_reviews(tmp_path):
    """read_pr_comments returns one ReviewComment per posted review."""
    (tmp_path / ".a2sdlc").mkdir()
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    adapter.post_review(1, body="hello", verdict="approved")
    comments = adapter.read_pr_comments(1)
    assert len(comments) == 1
    assert comments[0].author == "local"
    assert comments[0].body == "hello"
