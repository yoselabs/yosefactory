"""The seam: five methods, and nothing else may be called on an adapter (spec: "GitHub Issues
implements the adapter without becoming the interface").

architecture.md §7: "list_events(since) -> [Event] / project(item) / open(item) -> ref /
comment(ref, body) / close(ref, resolution)". `project` here takes the ref explicitly rather than
re-deriving it internally, so `project_all()` can `open()` once and reuse the ref for `project()`
and (when terminal) `close()` in the same pass without a second lookup -- an implementation detail
of who calls `open`, not a change to the four verbs the interface promises.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from yosefactory.board.event import Event
from yosefactory.protocol.eventlog import FoldedLog


class BoardAdapter(Protocol):
    """message + thread + state-field -- never issue + comment + label (architecture.md §7)."""

    def list_events(self, since: str | None) -> Sequence[Event]:
        """Unconsumed commands, oldest first. `since` is an opaque cursor this adapter defines
        (a timestamp for GitHub) -- callers never parse or compare it, only pass it back."""
        ...

    def open(self, item: FoldedLog) -> str:
        """Find-or-create the thread for `item`, idempotently, by searching the board itself --
        never a cache (design.md D2). Returns a ref stable across calls for the same item."""
        ...

    def project(self, item: FoldedLog, ref: str) -> None:
        """Sync the thread's title/body/state-field to `item`'s current fold. Idempotent."""
        ...

    def comment(self, ref: str, body: str) -> None:
        """Post a message on the thread. Used for rejections (design.md D5) and for narration."""
        ...

    def close(self, ref: str, resolution: str) -> None:
        """Set the thread's state-field to closed, naming why. Idempotent -- closing an
        already-closed thread with the same resolution is a no-op, not an error."""
        ...

    def propose(self, item: FoldedLog, ref: str, branch: str) -> str | None:
        """Open a change proposing `branch` for review against `ref`'s thread, if this forge has
        such a concept -- GitHub does, Jira does not. The capability is expressed by the return
        type, not by an exception or a separate probe method: `None` means "this adapter has
        nothing here," and every caller must already handle it before doing anything with the
        result, the same way it must handle any other `str | None`. An adapter that always
        returns `None` is a complete, correct implementation of this method, not a stub.

        Idempotent -- called twice for the same `branch` opens no second change (ADR-0016's
        marker-write-back pattern: search the board itself for one already open, never a cache)."""
        ...
