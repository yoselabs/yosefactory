"""git -> board, against the fake adapter. `test_reprojection.py` runs the same shape for real."""

from __future__ import annotations

from pathlib import Path

from yosefactory.board.projection import project_all
from yosefactory.protocol import backlog
from yosefactory.runtime import turn

from .fake_adapter import FakeAdapter

FRAME = {"goal": "ship the board", "method": "m", "assumptions": "a"}


def _seed_item(repo: Path, item_id: str, *, done: bool = False) -> None:
    (repo / turn.ITEMS).mkdir(parents=True, exist_ok=True)
    path = repo / turn.ITEMS / f"{item_id}.jsonl"
    turn.append(path, backlog.ITEM, {"event": "created", "loop": "l", "frame": FRAME}, actor="denis")
    if done:
        claim = {"event": "claimed", "owner": "o", "expires_at": "2099-01-01T00:00:00+00:00", "attempt": 1}
        turn.append(path, backlog.ITEM, claim, actor="o")
        turn.append(path, backlog.ITEM, {"event": "started"}, actor="o")
        turn.append(path, backlog.ITEM, {"event": "done", "effects": [], "verified_by": "test"}, actor="o")


def test_project_all_creates_one_thread_per_item(tmp_path: Path) -> None:
    _seed_item(tmp_path, "itm-a")
    _seed_item(tmp_path, "itm-b")
    adapter = FakeAdapter()

    refs = project_all(tmp_path, adapter)

    assert set(refs) == {"itm-a", "itm-b"}
    assert len(adapter.threads) == 2


def test_project_all_is_idempotent_on_ref(tmp_path: Path) -> None:
    _seed_item(tmp_path, "itm-a")
    adapter = FakeAdapter()

    first = project_all(tmp_path, adapter)
    second = project_all(tmp_path, adapter)

    assert first == second
    assert len(adapter.threads) == 1  # no second thread for the same item


def test_terminal_item_is_closed(tmp_path: Path) -> None:
    _seed_item(tmp_path, "itm-done", done=True)
    adapter = FakeAdapter()

    refs = project_all(tmp_path, adapter)

    assert adapter.threads[refs["itm-done"]].closed
    assert adapter.threads[refs["itm-done"]].resolution == "done"


def test_reprojection_after_destruction_matches(tmp_path: Path) -> None:
    """The acid test's own shape, against the fake -- see test_reprojection.py for the live one."""
    _seed_item(tmp_path, "itm-a")
    _seed_item(tmp_path, "itm-b", done=True)
    adapter = FakeAdapter()

    project_all(tmp_path, adapter)
    before = {thread.item_id: (thread.title, thread.state, thread.closed) for thread in adapter.threads.values()}

    adapter.destroy_all()
    project_all(tmp_path, adapter)
    after = {thread.item_id: (thread.title, thread.state, thread.closed) for thread in adapter.threads.values()}

    assert before == after
