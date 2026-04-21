"""Tests for StateManager."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from a2sdlc.domain.models import StageName, TicketState
from a2sdlc.lifecycle.state_storage import GitFileStateStorage
from tests.fakes import FakeGitAdapter


def _make_state(**kwargs: object) -> TicketState:
    """Build a minimal valid TicketState with sensible defaults."""
    defaults: dict[str, object] = {
        "stage": StageName.SPEC,
        "branch": "a2sdlc/PROJ-1",
        "stage_run_id": "run-001",
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    defaults.update(kwargs)
    return TicketState(**defaults)  # ty: ignore[invalid-argument-type]


@pytest.mark.unit
class TestReadState:
    def test_read_state_none_when_no_state(self) -> None:
        from a2sdlc.lifecycle.state import StateManager

        git = FakeGitAdapter(state_json=None)
        sm = StateManager(GitFileStateStorage(git), "PROJ-1")
        assert sm.read_state() is None

    def test_read_state_parses_stored_json(self) -> None:
        from a2sdlc.lifecycle.state import StateManager

        state = _make_state(stage=StageName.IMPLEMENT, stage_run_id="abc-123")
        json_str = state.model_dump_json()
        git = FakeGitAdapter(state_json=json_str)
        sm = StateManager(GitFileStateStorage(git), "PROJ-1")

        result = sm.read_state()
        assert result is not None
        assert result.stage == StageName.IMPLEMENT
        assert result.stage_run_id == "abc-123"

    def test_read_state_invalid_json_returns_none(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from a2sdlc.lifecycle.state import StateManager

        git = FakeGitAdapter(state_json="not-valid-json{{{")
        sm = StateManager(GitFileStateStorage(git), "PROJ-1")

        import logging

        with caplog.at_level(logging.WARNING, logger="a2sdlc.lifecycle.state"):
            result = sm.read_state()

        assert result is None
        assert any(
            "warn" in r.levelname.lower() or r.levelno >= logging.WARNING
            for r in caplog.records
        )


@pytest.mark.unit
class TestWriteState:
    def test_write_state_serializes_and_stores(self) -> None:
        from a2sdlc.lifecycle.state import StateManager

        git = FakeGitAdapter()
        sm = StateManager(GitFileStateStorage(git), "PROJ-1")
        state = _make_state(stage=StageName.REVIEW, stage_run_id="xyz")

        sm.write_state(state)

        assert len(git.written_state) == 1
        # Verify round-trip: parse what was written
        parsed = TicketState.model_validate_json(git.written_state[0])
        assert parsed.stage == StageName.REVIEW
        assert parsed.stage_run_id == "xyz"


@pytest.mark.unit
class TestCheckIdempotency:
    def test_matching_run_id_returns_true(self) -> None:
        from a2sdlc.lifecycle.state import StateManager

        state = _make_state(stage_run_id="run-42")
        git = FakeGitAdapter(state_json=state.model_dump_json())
        sm = StateManager(GitFileStateStorage(git), "PROJ-1")

        assert sm.check_idempotency("run-42") is True

    def test_different_run_id_returns_false(self) -> None:
        from a2sdlc.lifecycle.state import StateManager

        state = _make_state(stage_run_id="run-42")
        git = FakeGitAdapter(state_json=state.model_dump_json())
        sm = StateManager(GitFileStateStorage(git), "PROJ-1")

        assert sm.check_idempotency("run-99") is False

    def test_no_prior_state_returns_false(self) -> None:
        from a2sdlc.lifecycle.state import StateManager

        git = FakeGitAdapter(state_json=None)
        sm = StateManager(GitFileStateStorage(git), "PROJ-1")

        assert sm.check_idempotency("run-42") is False
