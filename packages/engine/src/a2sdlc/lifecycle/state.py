"""StateManager — read/write TicketState, idempotency checks."""

from __future__ import annotations

import logging

from a2sdlc.domain.models import TicketState
from a2sdlc.lifecycle.state_storage import StateStorage

logger = logging.getLogger("a2sdlc.lifecycle.state")


class StateManager:
    """Manages TicketState lifecycle: read, write, idempotency.

    Delegates persistence to a `StateStorage` backend so the pipeline
    ledger can live on the ticket branch (current), an orphan ref (GH
    phase 2), or dispatcher KV (Jira) without StateManager knowing.
    """

    def __init__(self, storage: StateStorage, key: str) -> None:
        self._storage = storage
        self._key = key

    def read_state(self) -> TicketState | None:
        """Read and parse TicketState from storage. Returns None if absent or invalid."""
        raw = self._storage.read(self._key)
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
        """Serialize TicketState to JSON and persist via storage backend."""
        self._storage.write(self._key, state.model_dump_json())

    def check_idempotency(self, stage_run_id: str) -> bool:
        """Return True if the current state's run_id matches (duplicate run)."""
        state = self.read_state()
        if state is None:
            return False
        return state.stage_run_id == stage_run_id
