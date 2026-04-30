"""Run-branch generator + parser. Spec §Run-branch suffix."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from a2sdlc.runtime.branch import (
    format_run_branch,
    parse_run_branch,
    compute_input_hash,
)


def test_format_run_branch_shape() -> None:
    ts = datetime(2026, 4, 30, 14, 22, 8, tzinfo=timezone.utc)
    branch = format_run_branch("req/billing-v2", ts, "a3f019")
    assert branch == "a2sdlc/auto/req-billing-v2/20260430-142208-a3f019"


def test_base_slug_replaces_slashes_with_hyphens() -> None:
    ts = datetime(2026, 4, 30, 14, 22, 8, tzinfo=timezone.utc)
    branch = format_run_branch("req/foo/bar", ts, "abcdef")
    assert "req-foo-bar" in branch


def test_parse_round_trip() -> None:
    ts = datetime(2026, 4, 30, 14, 22, 8, tzinfo=timezone.utc)
    branch = format_run_branch("req/billing-v2", ts, "a3f019")
    parsed = parse_run_branch(branch)
    assert parsed is not None
    assert parsed.base_slug == "req-billing-v2"
    assert parsed.ts == ts
    assert parsed.input_hash == "a3f019"


def test_parse_returns_none_for_non_run_branches() -> None:
    assert parse_run_branch("main") is None
    assert parse_run_branch("feature/foo") is None
    assert parse_run_branch("a2sdlc/auto/incomplete") is None


def test_compute_input_hash_first_six_hex_of_sha256() -> None:
    h = compute_input_hash(b"hello world")
    # SHA-256("hello world") = b94d27b9...
    assert h == "b94d27"
    assert len(h) == 6


def test_format_run_branch_uses_utc() -> None:
    # Naive datetime should be rejected to avoid TZ ambiguity.
    naive = datetime(2026, 4, 30, 14, 22, 8)
    with pytest.raises(ValueError):
        format_run_branch("req/x", naive, "abcdef")
