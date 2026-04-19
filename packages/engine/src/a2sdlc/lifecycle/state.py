"""StateManager — read/write TicketState, idempotency checks."""

from __future__ import annotations

import logging

from a2sdlc.adapters.git import GitAdapter
from a2sdlc.domain.models import TicketState

logger = logging.getLogger("a2sdlc.lifecycle.state")


class StateManager:
    """Manages TicketState lifecycle: read, write, idempotency."""

    def __init__(self, git: GitAdapter) -> None:
        self._git = git

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

    def check_idempotency(self, stage_run_id: str) -> bool:
        """Return True if the current state's run_id matches (duplicate run)."""
        state = self.read_state()
        if state is None:
            return False
        return state.stage_run_id == stage_run_id
