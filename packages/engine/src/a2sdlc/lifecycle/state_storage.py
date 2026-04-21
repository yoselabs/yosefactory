"""StateStorage — pluggable backend for pipeline ledger (state.json).

The pipeline ledger (run_id, pr_number, review_cycles, cost) is
tracker-agnostic data; only its storage medium differs. GitHub mode
writes to the ticket branch today; Jira mode will write to a dispatcher
KV. Phase 2 will add an orphan-ref GH backend so the ledger survives
branch deletion.

`StateStorage` is the surface StateManager talks to. Backends:
- `GitFileStateStorage` — current behavior, state.json on the ticket branch.
- `OrphanRefStateStorage` — future, `refs/a2sdlc/state/{key}`.
- `DispatcherKVStateStorage` — future, Jira mode.

The `key` parameter on read/write is the ticket key. File-based backends
ignore it (the checked-out branch already scopes it); ref-based and KV
backends use it directly.
"""

from __future__ import annotations

from typing import Protocol

from a2sdlc.adapters.git import GitAdapter


class StateStorage(Protocol):
    def read(self, key: str) -> str | None: ...
    def write(self, key: str, data: str) -> None: ...


class GitFileStateStorage:
    """File-on-branch backend — the current default.

    Ignores `key` because the checked-out branch already scopes which
    ticket's state.json is visible. Added when Phase-2 work starts using
    orphan refs to break this coupling.
    """

    def __init__(self, git: GitAdapter) -> None:
        self._git = git

    def read(self, key: str) -> str | None:
        del key
        return self._git.read_state()

    def write(self, key: str, data: str) -> None:
        del key
        self._git.write_state(data)
