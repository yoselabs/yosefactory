"""`BoardAdapter.propose`'s degradation contract: an adapter with no pull-request concept returns
`None` rather than raising or being skipped by a capability probe."""

from __future__ import annotations

from pathlib import Path

from yosefactory.protocol import backlog
from yosefactory.runtime import turn

from .fake_adapter import FakeAdapter

FRAME = {"goal": "ship the board", "method": "m", "assumptions": "a"}


def test_an_adapter_with_no_pull_request_concept_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "itm-a.jsonl"
    turn.append(path, backlog.ITEM, {"event": "created", "loop": "l", "frame": FRAME}, actor="denis")
    item = backlog.load(path)
    adapter = FakeAdapter()
    ref = adapter.open(item)

    result = adapter.propose(item, ref, "factory/itm-a")

    assert result is None
