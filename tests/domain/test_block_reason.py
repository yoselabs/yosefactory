"""Tests for BlockReason sum type — per-variant rendering + round-trip."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from a2sdlc.domain.block_reason import (
    AgentFailed,
    BlockReason,
    CostCeilingExceeded,
    Generic,
    GitCheckoutFailed,
    MergeConflict,
    NoStatusBlock,
    ReviewCyclesExceeded,
    StateSchemaTooNew,
)


BlockReasonAdapter = TypeAdapter(BlockReason)


@pytest.mark.unit
class TestReviewCyclesExceeded:
    def test_comment_matches_legacy_format(self) -> None:
        # Format mirrors pipeline/breakers.py::check_review_cycles so
        # migrating to the ADT is a no-op for subscribers.
        r = ReviewCyclesExceeded(cycles=3, maximum=2)
        assert r.as_comment() == "Circuit breaker: 3 review cycles exceeded max (2)"


@pytest.mark.unit
class TestCostCeilingExceeded:
    def test_comment_matches_legacy_format(self) -> None:
        r = CostCeilingExceeded(spent_usd=16.42, ceiling_usd=15.0)
        assert r.as_comment() == "Cost ceiling: $16.42 >= $15.00 per-ticket max"


@pytest.mark.unit
class TestMergeConflict:
    def test_comment(self) -> None:
        r = MergeConflict(base_branch="main")
        assert r.as_comment() == "merge conflict with main"


@pytest.mark.unit
class TestGitCheckoutFailed:
    def test_comment(self) -> None:
        r = GitCheckoutFailed(stderr="fatal: ref not found")
        assert r.as_comment() == "git checkout failed: fatal: ref not found"


@pytest.mark.unit
class TestNoStatusBlock:
    def test_comment(self) -> None:
        assert NoStatusBlock().as_comment() == "no status block in output"


@pytest.mark.unit
class TestAgentFailed:
    def test_comment_uses_error(self) -> None:
        assert AgentFailed(error="timeout after 60m").as_comment() == (
            "timeout after 60m"
        )

    def test_comment_empty_error_falls_back_to_unknown(self) -> None:
        # Matches current pipeline/stage_run.py behavior:
        #   mark_blocked(key, exec_result.error or "unknown")
        assert AgentFailed(error="").as_comment() == "unknown"


@pytest.mark.unit
class TestStateSchemaTooNew:
    def test_comment(self) -> None:
        r = StateSchemaTooNew(found=3, supported=2)
        comment = r.as_comment()
        assert "schema_version 3" in comment
        assert "version 2" in comment
        assert "upgrade the engine" in comment


@pytest.mark.unit
class TestGeneric:
    def test_comment(self) -> None:
        assert Generic(message="something else").as_comment() == "something else"


@pytest.mark.unit
class TestBlockReasonDiscriminatedUnion:
    def test_round_trip_each_variant(self) -> None:
        variants: list[BlockReason] = [
            ReviewCyclesExceeded(cycles=3, maximum=2),
            CostCeilingExceeded(spent_usd=16.0, ceiling_usd=15.0),
            MergeConflict(base_branch="main"),
            GitCheckoutFailed(stderr="bad"),
            NoStatusBlock(),
            AgentFailed(error="oops"),
            StateSchemaTooNew(found=3, supported=2),
            Generic(message="unknown"),
        ]
        for v in variants:
            restored = BlockReasonAdapter.validate_json(v.model_dump_json())
            assert type(restored) is type(v)
            assert restored.as_comment() == v.as_comment()

    def test_unknown_kind_rejected(self) -> None:
        with pytest.raises(Exception):
            BlockReasonAdapter.validate_json('{"kind":"xyz"}')

    def test_missing_kind_rejected(self) -> None:
        with pytest.raises(Exception):
            BlockReasonAdapter.validate_json('{"message":"hi"}')
