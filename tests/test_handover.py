"""Tests for handover comment parsing and pattern matching."""

from datetime import datetime, timezone

from a2sdlc.handover import (
    HANDOVER_PATTERN,
    later_stage,
    parse_handover,
)
from a2sdlc.models import StageName


def test_pattern_matches_all_stages():
    for stage in ("spec", "implement", "review", "merge"):
        text = f"### ✅ a2sdlc:{stage}"
        match = HANDOVER_PATTERN.search(text)
        assert match is not None, f"Pattern should match a2sdlc:{stage}"
        assert match.group(1) == stage


def test_pattern_rejects_unknown_stage():
    match = HANDOVER_PATTERN.search("### ✅ a2sdlc:deploy")
    assert match is None


def test_pattern_matches_in_progress_header():
    match = HANDOVER_PATTERN.search("### ⏳ a2sdlc:implement")
    assert match is not None
    assert match.group(1) == "implement"


def test_pattern_matches_error_header():
    match = HANDOVER_PATTERN.search("### 🚨 a2sdlc:review")
    assert match is not None
    assert match.group(1) == "review"


def test_parse_handover_success():
    body = "### ✅ a2sdlc:implement\n\n## Implementation Complete\n..."
    result = parse_handover(
        body, "c-123", datetime(2026, 4, 15, tzinfo=timezone.utc), "issue"
    )
    assert result is not None
    assert result.stage == StageName.IMPLEMENT
    assert result.run_id == "c-123"
    assert result.location == "issue"


def test_parse_handover_not_a_handover():
    body = "Just a regular comment about the code."
    result = parse_handover(
        body, "c-456", datetime(2026, 4, 15, tzinfo=timezone.utc), "issue"
    )
    assert result is None


def test_later_stage():
    assert later_stage(StageName.SPEC, StageName.IMPLEMENT) == StageName.IMPLEMENT
    assert later_stage(StageName.REVIEW, StageName.IMPLEMENT) == StageName.REVIEW
    assert later_stage(StageName.MERGE, StageName.SPEC) == StageName.MERGE
