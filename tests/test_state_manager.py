"""Tests for StateManager."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from a2sdlc.config import get_session_id
from a2sdlc.models import StageName, TicketState
from tests.fakes_v2 import FakeGitAdapter


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
        from a2sdlc.state_manager import StateManager

        git = FakeGitAdapter(state_json=None)
        sm = StateManager(git)
        assert sm.read_state() is None

    def test_read_state_parses_stored_json(self) -> None:
        from a2sdlc.state_manager import StateManager

        state = _make_state(stage=StageName.IMPLEMENT, stage_run_id="abc-123")
        json_str = state.model_dump_json()
        git = FakeGitAdapter(state_json=json_str)
        sm = StateManager(git)

        result = sm.read_state()
        assert result is not None
        assert result.stage == StageName.IMPLEMENT
        assert result.stage_run_id == "abc-123"

    def test_read_state_invalid_json_returns_none(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from a2sdlc.state_manager import StateManager

        git = FakeGitAdapter(state_json="not-valid-json{{{")
        sm = StateManager(git)

        import logging

        with caplog.at_level(logging.WARNING, logger="a2sdlc.state_manager"):
            result = sm.read_state()

        assert result is None
        assert any(
            "warn" in r.levelname.lower() or r.levelno >= logging.WARNING
            for r in caplog.records
        )


@pytest.mark.unit
class TestWriteState:
    def test_write_state_serializes_and_stores(self) -> None:
        from a2sdlc.state_manager import StateManager

        git = FakeGitAdapter()
        sm = StateManager(git)
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
        from a2sdlc.state_manager import StateManager

        state = _make_state(stage_run_id="run-42")
        git = FakeGitAdapter(state_json=state.model_dump_json())
        sm = StateManager(git)

        assert sm.check_idempotency("run-42") is True

    def test_different_run_id_returns_false(self) -> None:
        from a2sdlc.state_manager import StateManager

        state = _make_state(stage_run_id="run-42")
        git = FakeGitAdapter(state_json=state.model_dump_json())
        sm = StateManager(git)

        assert sm.check_idempotency("run-99") is False

    def test_no_prior_state_returns_false(self) -> None:
        from a2sdlc.state_manager import StateManager

        git = FakeGitAdapter(state_json=None)
        sm = StateManager(git)

        assert sm.check_idempotency("run-42") is False


@pytest.mark.unit
class TestGenerateRunId:
    def test_github_run_id_and_attempt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from a2sdlc.state_manager import StateManager

        monkeypatch.setenv("GITHUB_RUN_ID", "12345")
        monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "3")
        monkeypatch.delenv("A2SDLC_RUN_ID", raising=False)

        git = FakeGitAdapter()
        sm = StateManager(git)

        assert sm.generate_run_id() == "12345-3"

    def test_a2sdlc_run_id_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from a2sdlc.state_manager import StateManager

        monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
        monkeypatch.delenv("GITHUB_RUN_ATTEMPT", raising=False)
        monkeypatch.setenv("A2SDLC_RUN_ID", "custom-run-id")

        git = FakeGitAdapter()
        sm = StateManager(git)

        assert sm.generate_run_id() == "custom-run-id"

    def test_fallback_random_uuid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from a2sdlc.state_manager import StateManager

        monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
        monkeypatch.delenv("GITHUB_RUN_ATTEMPT", raising=False)
        monkeypatch.delenv("A2SDLC_RUN_ID", raising=False)

        git = FakeGitAdapter()
        sm = StateManager(git)

        run_id = sm.generate_run_id()
        # Must be a valid UUID string
        parsed = uuid.UUID(run_id)
        assert str(parsed) == run_id

    def test_github_run_id_without_attempt_uses_a2sdlc_run_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only GITHUB_RUN_ID set (no attempt) — falls through to A2SDLC_RUN_ID."""
        from a2sdlc.state_manager import StateManager

        monkeypatch.setenv("GITHUB_RUN_ID", "12345")
        monkeypatch.delenv("GITHUB_RUN_ATTEMPT", raising=False)
        monkeypatch.setenv("A2SDLC_RUN_ID", "fallback-id")

        git = FakeGitAdapter()
        sm = StateManager(git)

        assert sm.generate_run_id() == "fallback-id"


@pytest.mark.unit
class TestGetSessionId:
    def test_delegates_to_config_get_session_id(self) -> None:
        from a2sdlc.state_manager import StateManager

        git = FakeGitAdapter()
        sm = StateManager(git)

        expected = get_session_id("PROJ-10", "spec", 0)
        result = sm.get_session_id("PROJ-10", "spec", review_cycles=0)
        assert result == expected

    def test_delegates_with_review_cycles(self) -> None:
        from a2sdlc.state_manager import StateManager

        git = FakeGitAdapter()
        sm = StateManager(git)

        expected = get_session_id("PROJ-10", "review", 2)
        result = sm.get_session_id("PROJ-10", "review", review_cycles=2)
        assert result == expected

    def test_review_cycles_default_zero(self) -> None:
        from a2sdlc.state_manager import StateManager

        git = FakeGitAdapter()
        sm = StateManager(git)

        assert sm.get_session_id("PROJ-1", "spec") == get_session_id(
            "PROJ-1", "spec", 0
        )
