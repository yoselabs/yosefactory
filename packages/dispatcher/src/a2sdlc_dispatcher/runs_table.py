"""In-memory runs table.

Tracks run_id → (ticket_key, repo, project_key). Populated when a Jira
webhook triggers a workflow; consulted when the engine POSTs domain
events so we can resolve back to the correct Jira ticket and project.

Ephemeral: dies on restart. If the dispatcher restarts mid-run, the
in-flight run's domain events will 404 at `/runs/{run_id}/events` — the
engine's subscriber ignores 4xx and the pipeline still finishes with
comments posted elsewhere (console, MLflow). Accepted tradeoff for v1.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock


class RunNotFound(KeyError):
    """Raised when get() is called with an unknown run_id."""


@dataclass(frozen=True)
class RunEntry:
    run_id: str
    ticket_key: str
    repo: str
    project_key: str


class RunsTable:
    def __init__(self) -> None:
        self._by_run: dict[str, RunEntry] = {}
        self._by_ticket: dict[str, str] = {}
        self._in_progress_sent: set[str] = set()
        self._lock = RLock()

    def register(
        self, *, run_id: str, ticket_key: str, repo: str, project_key: str
    ) -> None:
        with self._lock:
            entry = RunEntry(
                run_id=run_id, ticket_key=ticket_key, repo=repo, project_key=project_key
            )
            self._by_run[run_id] = entry
            self._by_ticket[ticket_key] = run_id

    def get(self, run_id: str) -> RunEntry:
        try:
            return self._by_run[run_id]
        except KeyError:
            raise RunNotFound(run_id) from None

    def finish(self, run_id: str) -> None:
        with self._lock:
            entry = self._by_run.pop(run_id, None)
            self._in_progress_sent.discard(run_id)
            if entry and self._by_ticket.get(entry.ticket_key) == run_id:
                self._by_ticket.pop(entry.ticket_key, None)

    def active_run_for(self, ticket_key: str) -> str | None:
        with self._lock:
            return self._by_ticket.get(ticket_key)

    def mark_in_progress_sent(self, run_id: str) -> None:
        """Idempotent — flag that this run has already had its In Progress transition applied."""
        with self._lock:
            self._in_progress_sent.add(run_id)

    def has_in_progress_been_sent(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._in_progress_sent
