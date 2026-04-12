"""StateManager — read/write TicketState, generate session/run IDs."""

from __future__ import annotations

import logging
import os
import uuid

from a2sdlc.adapters.protocols import GitAdapter
from a2sdlc.config import get_session_id
from a2sdlc.models import TicketState

logger = logging.getLogger("a2sdlc.state_manager")


class StateManager:
    """Manages TicketState lifecycle: read, write, idempotency, ID generation."""

    def __init__(self, git: GitAdapter) -> None:
        self._git = git

    # ── State I/O ─────────────────────────────────────────────────────

    def read_state(self) -> TicketState | None:
        """Read and parse TicketState from git. Returns None if absent or invalid."""
        raw = self._git.read_state()
        if raw is None:
            return None
        try:
            return TicketState.model_validate_json(raw)
        except Exception:
            logger.warning(
                "state_manager.read_state: failed to parse state JSON", exc_info=True
            )
            return None

    def write_state(self, state: TicketState) -> None:
        """Serialize TicketState to JSON and persist via git adapter."""
        self._git.write_state(state.model_dump_json())

    # ── Idempotency ───────────────────────────────────────────────────

    def check_idempotency(self, stage_run_id: str) -> bool:
        """Return True if the current state's run_id matches (duplicate run)."""
        state = self.read_state()
        if state is None:
            return False
        return state.stage_run_id == stage_run_id

    # ── ID generation ─────────────────────────────────────────────────

    def generate_run_id(self) -> str:
        """Generate a run ID.

        Priority:
        1. ``GITHUB_RUN_ID`` + ``GITHUB_RUN_ATTEMPT`` → ``{run_id}-{attempt}``
        2. ``A2SDLC_RUN_ID`` env var
        3. Random UUID
        """
        github_run_id = os.environ.get("GITHUB_RUN_ID")
        github_run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT")
        if github_run_id and github_run_attempt:
            return f"{github_run_id}-{github_run_attempt}"

        a2sdlc_run_id = os.environ.get("A2SDLC_RUN_ID")
        if a2sdlc_run_id:
            return a2sdlc_run_id

        return str(uuid.uuid4())

    def get_session_id(
        self, ticket_key: str, stage: str, review_cycles: int = 0
    ) -> str:
        """Deterministic session ID — delegates to ``a2sdlc.config.get_session_id``."""
        return get_session_id(ticket_key, stage, review_cycles)
