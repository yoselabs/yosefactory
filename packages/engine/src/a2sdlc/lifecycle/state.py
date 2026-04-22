"""StateManager — read/write TicketState, idempotency checks."""

from __future__ import annotations

import json
import logging

from a2sdlc.domain.exceptions import StateSchemaRegression, StateSchemaTooNew
from a2sdlc.domain.models import TicketState
from a2sdlc.lifecycle.state_migrations import (
    CURRENT_SCHEMA_VERSION,
    apply_migrations,
)
from a2sdlc.lifecycle.state_storage import StateStorage

logger = logging.getLogger("a2sdlc.lifecycle.state")


class StateManager:
    """Manages TicketState lifecycle: read, write, idempotency.

    Delegates persistence to a `StateStorage` backend so the pipeline
    ledger can live on the ticket branch (current), an orphan ref (GH
    phase 2), or dispatcher KV (Jira) without StateManager knowing.

    Reads route through ``apply_migrations`` per ADR-0005 — documents
    lacking ``schema_version`` are treated as v1 and upgraded on first
    read. Newer-than-supported documents raise ``StateSchemaTooNew``.
    """

    def __init__(self, storage: StateStorage, key: str) -> None:
        self._storage = storage
        self._key = key

    def read_state(self) -> TicketState | None:
        """Read, migrate, and parse TicketState from storage.

        Returns None if absent or malformed JSON. Raises
        ``StateSchemaTooNew`` for documents ahead of this engine's
        supported schema version (permanent error per ADR-0005).
        """
        raw = self._storage.read(self._key)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(
                "state_manager.read_state: failed to parse state JSON",
                exc_info=True,
            )
            return None
        if not isinstance(data, dict):
            logger.warning(
                "state_manager.read_state: state JSON is not an object",
            )
            return None
        migrated = apply_migrations(data)
        try:
            return TicketState.model_validate(migrated)
        except Exception:
            logger.warning(
                "state_manager.read_state: failed to validate migrated state",
                exc_info=True,
            )
            return None

    def write_state(self, state: TicketState) -> None:
        """Serialize TicketState to JSON and persist via storage backend.

        Enforces ADR-0005 invariant I7 — schema_version monotonically
        increases within a ticket's lifetime. Raises
        ``StateSchemaRegression`` if the incoming state's schema_version
        is older than what is already persisted.
        """
        raw_existing = self._storage.read(self._key)
        if raw_existing is not None:
            try:
                existing = json.loads(raw_existing)
            except json.JSONDecodeError:
                existing = None
            if isinstance(existing, dict):
                existing_version = existing.get("schema_version", 1)
                # Check "too new" before "regression" — if persisted state
                # is ahead of the engine's support, the diagnosis is
                # "upgrade the engine," not "you tried to downgrade."
                if existing_version > CURRENT_SCHEMA_VERSION:
                    raise StateSchemaTooNew(
                        found=existing_version,
                        supported=CURRENT_SCHEMA_VERSION,
                    )
                if state.schema_version < existing_version:
                    raise StateSchemaRegression(
                        existing=existing_version,
                        attempted=state.schema_version,
                    )
        self._storage.write(self._key, state.model_dump_json())

    def check_idempotency(self, stage_run_id: str) -> bool:
        """Return True if the current state's run_id matches (duplicate run)."""
        state = self.read_state()
        if state is None:
            return False
        return state.stage_run_id == stage_run_id
