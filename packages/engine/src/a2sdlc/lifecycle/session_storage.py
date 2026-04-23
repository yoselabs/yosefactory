"""SessionStorage Protocol — pluggable backend for Claude Agent SDK session data.

Architecture vision Q7. Today the Claude SDK persists session blobs on
local disk at ``.a2sdlc/tickets/{key}/`` and the engine does not
abstract that. Adding a Protocol + ``LocalDiskSessionStorage`` default
here — zero behavior change today — is the H2 seam for external
session storage (Redis / Postgres) in the Temporal edition. Without it
the H2 migration would face an unabstracted corpus of on-disk blobs.

P2 step 3. No call-site adoption in V1.0 beyond ``LocalDiskSessionStorage``
being available from the composition profile; the adapter layer keeps
passing ``session_id`` to the SDK and trusting the SDK's default
on-disk behavior.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SessionStorage(Protocol):
    """Backend for Claude SDK session persistence.

    Session blobs are opaque bytes from the engine's perspective — the
    SDK produces and consumes them. This Protocol is purely transport.

    Impls document their consistency model in their docstring (same rule
    as ``StateStorage``; see ADR-0005 invariant I8).
    """

    def save(self, session_id: str, data: bytes) -> None: ...
    def load(self, session_id: str) -> bytes | None: ...
    def purge(self, session_id: str) -> None: ...


class LocalDiskSessionStorage:
    """On-disk session storage under a project-scoped directory.

    Default V1.0 backend. Files live at ``<root>/<session_id>``;
    ``session_id`` is treated as a filename (SDK derives it deterministically
    so cross-session collisions are not an engine concern).

    Consistency: single-writer per session. Concurrent writes to the same
    session_id are serialized by the CI concurrency group (same model as
    ``GitFileStateStorage`` per ADR-0005 I6). Cross-session writes are
    independent.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def save(self, session_id: str, data: bytes) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        (self._root / session_id).write_bytes(data)

    def load(self, session_id: str) -> bytes | None:
        path = self._root / session_id
        if not path.is_file():
            return None
        return path.read_bytes()

    def purge(self, session_id: str) -> None:
        path = self._root / session_id
        if path.is_file():
            path.unlink()


__all__ = ["LocalDiskSessionStorage", "SessionStorage"]
