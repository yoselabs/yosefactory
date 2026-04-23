"""Behavior tests for local_noop_review adapter."""

import json
import subprocess
from datetime import datetime, timedelta, timezone

from a2sdlc.adapters.review.local_noop import LocalNoopReviewAdapter
from a2sdlc.adapters.review import Approval
from a2sdlc.domain.stage_outcome import InlineComment


def test_create_draft_pr_writes_pr_json(tmp_path):
    """GIVEN a fresh project root
    WHEN create_draft_pr is called
    THEN .a2sdlc/state/pr.json exists with pr_number=1 and status=draft."""
    (tmp_path / ".a2sdlc" / "state").mkdir(parents=True)
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)

    pr_number = adapter.create_draft_pr(
        branch="a2sdlc/sid", base="main", title="title", ticket_key="sid"
    )

    assert pr_number == 1
    data = json.loads((tmp_path / ".a2sdlc" / "state" / "pr.json").read_text())
    assert data["pr_number"] == 1
    assert data["status"] == "draft"
    assert data["title"] == "title"


def test_get_approvals_returns_local_non_bot(tmp_path):
    """Synthetic approval that satisfies check_human_approval."""
    (tmp_path / ".a2sdlc" / "state").mkdir(parents=True)
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    approvals = adapter.get_approvals(1)
    assert approvals == [Approval(user="local", is_bot=False)]


def test_post_review_changes_requested_writes_feedback(tmp_path):
    """changes_requested → feedback.json with consumed=false."""
    (tmp_path / ".a2sdlc" / "state").mkdir(parents=True)
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    adapter.post_review(1, body="Needs work", verdict="changes_requested")

    fb = json.loads((tmp_path / ".a2sdlc" / "state" / "feedback.json").read_text())
    assert fb["consumed"] is False
    assert "Needs work" in fb["body"]


def test_post_review_approved_does_not_write_feedback(tmp_path):
    """approved → feedback.json NOT written."""
    (tmp_path / ".a2sdlc" / "state").mkdir(parents=True)
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    adapter.post_review(1, body="LGTM", verdict="approved")
    assert not (tmp_path / ".a2sdlc" / "state" / "feedback.json").exists()


def test_collect_pr_feedback_filters_by_since(tmp_path):
    """since > feedback.created_at → empty."""
    (tmp_path / ".a2sdlc" / "state").mkdir(parents=True)
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    adapter.post_review(1, "fix this", "changes_requested")
    since = datetime.now(timezone.utc) + timedelta(hours=1)
    assert adapter.collect_pr_feedback(1, since) == []


def test_collect_pr_feedback_returns_when_since_is_before(tmp_path):
    """since < feedback.created_at → returns one FeedbackItem."""
    (tmp_path / ".a2sdlc" / "state").mkdir(parents=True)
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    adapter.post_review(1, "fix it", "changes_requested")
    items = adapter.collect_pr_feedback(1, datetime.min.replace(tzinfo=timezone.utc))
    assert len(items) == 1
    assert "fix it" in items[0].body


def test_collect_pr_feedback_does_not_consume(tmp_path):
    """Adapter is read-only — runner flips consumed after success."""
    (tmp_path / ".a2sdlc" / "state").mkdir(parents=True)
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    adapter.post_review(1, "fix", "changes_requested")
    adapter.collect_pr_feedback(1, datetime.min.replace(tzinfo=timezone.utc))
    fb = json.loads((tmp_path / ".a2sdlc" / "state" / "feedback.json").read_text())
    assert fb["consumed"] is False


def test_collect_pr_feedback_respects_consumed_flag(tmp_path):
    """When feedback is already consumed → empty list."""
    (tmp_path / ".a2sdlc" / "state").mkdir(parents=True)
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    adapter.post_review(1, "fix", "changes_requested")
    adapter.mark_feedback_consumed()
    items = adapter.collect_pr_feedback(1, datetime.min.replace(tzinfo=timezone.utc))
    assert items == []


def test_merge_pr_updates_status(tmp_path):
    """merge_pr → pr.json.status = 'merged'."""
    (tmp_path / ".a2sdlc" / "state").mkdir(parents=True)
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    adapter.merge_pr(1)
    data = json.loads((tmp_path / ".a2sdlc" / "state" / "pr.json").read_text())
    assert data["status"] == "merged"


def test_mark_pr_ready_updates_status(tmp_path):
    """mark_pr_ready → pr.json.status = 'ready'."""
    (tmp_path / ".a2sdlc" / "state").mkdir(parents=True)
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    adapter.mark_pr_ready(1)
    data = json.loads((tmp_path / ".a2sdlc" / "state" / "pr.json").read_text())
    assert data["status"] == "ready"


def test_find_last_handover_returns_none(tmp_path):
    """PR-side handover is not used locally — always None."""
    (tmp_path / ".a2sdlc" / "state").mkdir(parents=True)
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
    (tmp_path / ".a2sdlc" / "state").mkdir(parents=True)

    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    diff = adapter.read_pr_diff(1)
    assert isinstance(diff, str)


def test_update_pr_updates_fields(tmp_path):
    """update_pr edits title/body/ticket_key in pr.json."""
    (tmp_path / ".a2sdlc" / "state").mkdir(parents=True)
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "old", "sid")
    adapter.update_pr(1, title="new", body="new body", ticket_key="sid")
    data = json.loads((tmp_path / ".a2sdlc" / "state" / "pr.json").read_text())
    assert data["title"] == "new"
    assert data["body"] == "new body"


def test_read_pr_comments_maps_reviews(tmp_path):
    """read_pr_comments returns one ReviewComment per posted review."""
    (tmp_path / ".a2sdlc" / "state").mkdir(parents=True)
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    adapter.post_review(1, body="hello", verdict="approved")
    comments = adapter.read_pr_comments(1)
    assert len(comments) == 1
    assert comments[0].author == "local"
    assert comments[0].body == "hello"


def test_collect_pr_feedback_returns_empty_when_no_feedback_file(tmp_path):
    """GIVEN pr.json exists but no feedback.json
    WHEN collect_pr_feedback is called
    THEN it returns [] (file-existence guard)."""
    (tmp_path / ".a2sdlc" / "state").mkdir(parents=True)
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")

    assert adapter.collect_pr_feedback(1, datetime.now(timezone.utc)) == []


def test_mark_feedback_consumed_is_noop_when_file_missing(tmp_path):
    """GIVEN no feedback.json
    WHEN mark_feedback_consumed is called
    THEN it returns without crashing and creates no file."""
    (tmp_path / ".a2sdlc" / "state").mkdir(parents=True)
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)

    adapter.mark_feedback_consumed()  # must not raise

    assert not (tmp_path / ".a2sdlc" / "state" / "feedback.json").exists()


def test_collect_pr_feedback_parses_naive_iso_as_utc(tmp_path):
    """GIVEN feedback.json with a naive (no tz) ISO created_at
    WHEN collect_pr_feedback is called with a since older than that
    THEN _parse_iso assumes UTC and the item is returned."""
    (tmp_path / ".a2sdlc" / "state").mkdir(parents=True)
    # Write feedback.json directly with a naive ISO timestamp.
    naive_iso = "2099-01-01T00:00:00"  # far in the future, naive
    (tmp_path / ".a2sdlc" / "state" / "feedback.json").write_text(
        json.dumps(
            {
                "consumed": False,
                "body": "naive feedback",
                "cycle": 1,
                "created_at": naive_iso,
            }
        )
    )

    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    items = adapter.collect_pr_feedback(1, datetime(2000, 1, 1, tzinfo=timezone.utc))

    assert len(items) == 1
    assert items[0].body == "naive feedback"
    # _parse_iso should have promoted to tz-aware UTC.
    assert items[0].created_at.tzinfo is not None


def test_collect_pr_feedback_promotes_naive_since_to_utc(tmp_path):
    """GIVEN feedback.json with an aware created_at
    WHEN collect_pr_feedback is called with a NAIVE since well in the future
    THEN _ensure_aware promotes since to UTC and the item is filtered out."""
    (tmp_path / ".a2sdlc" / "state").mkdir(parents=True)
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    adapter.post_review(1, "fix", "changes_requested")

    # Naive datetime in the far future — must be promoted to UTC for the
    # comparison; otherwise a TypeError would surface.
    naive_future = datetime(2999, 1, 1)
    items = adapter.collect_pr_feedback(1, naive_future)

    assert items == []


def test_post_inline_comments_empty_list_is_noop(tmp_path):
    """Empty list must not touch pr.json."""
    (tmp_path / ".a2sdlc" / "state").mkdir(parents=True)
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    before = (tmp_path / ".a2sdlc" / "state" / "pr.json").read_text()

    adapter.post_inline_comments(1, [])

    after = (tmp_path / ".a2sdlc" / "state" / "pr.json").read_text()
    assert before == after


def test_post_inline_comments_appends_to_pr_json(tmp_path):
    """Comments land under pr.json['inline_comments'] with shape fields."""
    (tmp_path / ".a2sdlc" / "state").mkdir(parents=True)
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")

    adapter.post_inline_comments(
        1,
        [
            InlineComment(
                file="src/app.py", line_start=1, line_end=3, body="trim", side="RIGHT"
            )
        ],
    )

    data = json.loads((tmp_path / ".a2sdlc" / "state" / "pr.json").read_text())
    assert len(data["inline_comments"]) == 1
    rec = data["inline_comments"][0]
    assert rec["file"] == "src/app.py"
    assert rec["line_start"] == 1
    assert rec["line_end"] == 3
    assert rec["side"] == "RIGHT"
    assert rec["body"] == "trim"
    assert "created_at" in rec
