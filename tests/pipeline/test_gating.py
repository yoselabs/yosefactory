"""L1 tests for pipeline.gating — ticket-active + idempotency checks.

Circuit-breaker checks (review-cycles, cost-ceiling) are tested via
their dedicated pipeline.breakers tests and exercised end-to-end by
the dispatch integration suite; gating just re-exports them.
"""

from __future__ import annotations

from pathlib import Path

from a2sdlc.domain.pipeline_event import PipelineEvent
from a2sdlc.lifecycle.state import StateManager
from a2sdlc.lifecycle.state_storage import GitFileStateStorage
from a2sdlc.pipeline.gating import (
    check_duplicate_run_id,
    check_ticket_active,
)
from tests.fakes import make_dispatch_context


def test_check_ticket_active_returns_reason_when_closed() -> None:
    ctx, work, *_ = make_dispatch_context(project_root=Path("/tmp/test_gating_closed"))
    work._is_active = False  # type: ignore[attr-defined]
    event = PipelineEvent(key="35")

    assert check_ticket_active(ctx, event) == "ticket_not_active"


def test_check_ticket_active_returns_none_when_open() -> None:
    ctx, *_ = make_dispatch_context(project_root=Path("/tmp/test_gating_open"))
    event = PipelineEvent(key="35")

    assert check_ticket_active(ctx, event) is None


def test_check_duplicate_run_id_returns_reason_when_stale() -> None:
    """check_idempotency returning True means this run_id already produced
    an outcome — gating returns the idempotency-skip label."""
    state_json = (
        '{"stage":"spec","branch":"agent/35","stage_run_id":"run-dup",'
        '"last_updated":"2026-04-25T00:00:00Z"}'
    )
    ctx, _work, git, *_ = make_dispatch_context(
        state_json=state_json, project_root=Path("/tmp/test_gating_dup")
    )
    state_mgr = StateManager(GitFileStateStorage(git), "35")

    assert check_duplicate_run_id(ctx, state_mgr, "run-dup") == "duplicate_run_id"


def test_check_duplicate_run_id_returns_none_when_run_id_new() -> None:
    state_json = (
        '{"stage":"spec","branch":"agent/35","stage_run_id":"run-prior",'
        '"last_updated":"2026-04-25T00:00:00Z"}'
    )
    ctx, _work, git, *_ = make_dispatch_context(
        state_json=state_json, project_root=Path("/tmp/test_gating_new")
    )
    state_mgr = StateManager(GitFileStateStorage(git), "35")

    assert check_duplicate_run_id(ctx, state_mgr, "run-fresh") is None


def test_check_duplicate_run_id_returns_none_when_run_id_missing() -> None:
    """No run_id passed → nothing to compare against → not a duplicate."""
    ctx, _work, git, *_ = make_dispatch_context(
        project_root=Path("/tmp/test_gating_no_runid")
    )
    state_mgr = StateManager(GitFileStateStorage(git), "35")

    assert check_duplicate_run_id(ctx, state_mgr, None) is None
