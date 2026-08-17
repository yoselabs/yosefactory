"""git -> board. A read-only mirror, and the module the re-projection acid test exercises.

architecture.md §7's acid test, restated as code: "if the whole board can be deleted and
re-projected from git, it is a read model; if not, it is a second master." `project_all()` is
written so that claim is checkable rather than assumed -- its only read is `runtime.turn.items()`
(backlog items off disk), its only write is through `BoardAdapter`, and `open()`'s own ref
resolution (design.md D2) has no cache for a destroyed-and-rebuilt board to disagree with.

Never call `adapter.list_events()` from here. That is `inbox.py`'s side of the seam, and the
architecture's own rule -- "the reducer reads git to decide, never the board" -- is enforced
structurally by this module simply not importing anything that reads commands.
"""

from __future__ import annotations

from pathlib import Path

from yosefactory.board.adapter import BoardAdapter
from yosefactory.protocol.eventlog import FoldedLog
from yosefactory.runtime.turn import items as backlog_items


def project_all(repo: Path, adapter: BoardAdapter) -> dict[str, str]:
    """Ensure the board reflects every backlog item's current fold. Returns {item_id: ref}.

    Safe to call repeatedly and from an empty board (the acid test's own second pass): `open()`
    is the idempotent half, `project()`/`close()` are unconditionally re-applied every call
    because "the board reflects git" has no cheaper truth to check it against than re-asserting
    it -- a partial sync that skipped an unchanged item would still be correct today and silently
    stale the next time `project()`'s own rendering logic changes.
    """
    refs: dict[str, str] = {}
    for item in backlog_items(repo):
        ref = project_one(adapter, item)
        refs[item.id] = ref
    return refs


def project_one(adapter: BoardAdapter, item: FoldedLog) -> str:
    ref = adapter.open(item)
    adapter.project(item, ref)
    if item.terminal:
        adapter.close(ref, item.state)
    return ref
