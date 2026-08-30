"""An in-memory `BoardAdapter` for unit tests -- same Protocol, no network, no `gh`.

Mirrors the GitHub adapter's own no-cache discipline (design.md D2): `open()` searches its own
`threads` dict by item id rather than trusting a caller-supplied ref, so a test that "deletes"
threads and re-projects exercises the same code shape the live acid test does, just against a
dict instead of a real repo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from yosefactory.board.event import Event
from yosefactory.protocol.backlog import frame
from yosefactory.protocol.eventlog import FoldedLog


@dataclass
class Thread:
    item_id: str
    title: str = ""
    body: str = ""
    state: str = ""
    closed: bool = False
    resolution: str | None = None
    comments: list[str] = field(default_factory=list)


class FakeAdapter:
    def __init__(self) -> None:
        self.threads: dict[str, Thread] = {}  # ref -> Thread
        self._by_item: dict[str, str] = {}  # item_id -> ref
        self._counter = 0
        self.queued_events: list[Event] = []

    def destroy_all(self) -> None:
        """The acid test's "delete every issue" step, against this fake."""
        self.threads.clear()
        self._by_item.clear()

    def open(self, item: FoldedLog) -> str:
        existing = self._by_item.get(item.id)
        if existing is not None and existing in self.threads:
            return existing
        self._counter += 1
        ref = str(self._counter)
        self.threads[ref] = Thread(item_id=item.id)
        self._by_item[item.id] = ref
        return ref

    def project(self, item: FoldedLog, ref: str) -> None:
        thread = self.threads[ref]
        thread.title = f"[{item.state}] {frame(item).get('goal', '')}"
        thread.state = item.state

    def comment(self, ref: str, body: str) -> None:
        self.threads[ref].comments.append(body)

    def close(self, ref: str, resolution: str) -> None:
        thread = self.threads[ref]
        thread.closed = True
        thread.resolution = resolution

    def propose(self, item: FoldedLog, ref: str, branch: str) -> str | None:
        """Models a forge with no pull-request concept (Jira, e.g.) -- always `None`, the
        degradation path every `BoardAdapter` caller must already handle."""
        return None

    def list_events(self, since: str | None) -> list[Event]:
        pending = [event for event in self.queued_events if since is None or event.ts > since]
        return sorted(pending, key=lambda event: event.ts)
