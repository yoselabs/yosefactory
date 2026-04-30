"""LocalReviewAdapter: writes review markdown into branch state."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from a2sdlc.adapters.review.local import LocalReviewAdapter
from a2sdlc.domain.stage_outcome import InlineComment


def make_adapter(tmp_path: Path) -> LocalReviewAdapter:
    return LocalReviewAdapter(
        state_root=tmp_path / ".a2sdlc/state/branchA",
        clock=lambda: datetime(2026, 4, 30, 14, 22, 8, tzinfo=timezone.utc),
        cycle=1,
    )


def test_post_review_writes_cycle_file_and_returns_path(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path)
    p = adapter.post_review(pr_number=0, body="approved", verdict="approved")
    assert (
        p == tmp_path / ".a2sdlc/state/branchA/reviews/2026-04-30T14-22-08-cycle-1.md"
    )
    assert p.exists()
    assert "verdict: approved" in p.read_text()
    assert "approved" in p.read_text()


def test_post_inline_comments_writes_paired_inline_file(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path)
    adapter.post_inline_comments(
        pr_number=0,
        comments=[
            InlineComment(
                file="src/x.py", line_start=42, line_end=42, body="check this"
            ),
            InlineComment(
                file="src/y.py", line_start=7, line_end=7, body="multi\nline"
            ),
        ],
    )
    inline = (
        tmp_path / ".a2sdlc/state/branchA/reviews/2026-04-30T14-22-08-cycle-1-inline.md"
    )
    text = inline.read_text()
    assert "src/x.py:42" in text
    assert "  agent: check this" in text
    assert "src/y.py:7" in text
    assert "  agent: multi\n  line" in text


def test_post_inline_comments_empty_list_is_noop(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path)
    adapter.post_inline_comments(pr_number=0, comments=[])
    inline = (
        tmp_path / ".a2sdlc/state/branchA/reviews/2026-04-30T14-22-08-cycle-1-inline.md"
    )
    assert not inline.exists()


def test_pr_lifecycle_methods_are_safe_noops(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path)
    assert adapter.create_draft_pr(branch="x", base="y", title="t", ticket_key="K") == 0
    assert adapter.get_approvals(pr_number=0) == []
    adapter.update_pr(pr_number=0, title="t", body="b", ticket_key="K")
    adapter.update_pr_title(pr_number=0, title="t")
    adapter.mark_pr_ready(pr_number=0)
    adapter.merge_pr(pr_number=0)
