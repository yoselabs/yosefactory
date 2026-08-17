from __future__ import annotations

from pathlib import Path

from yosefactory.board.event import Event
from yosefactory.board.inbox import CONSUMED_LOG, ingest
from yosefactory.protocol import backlog, question
from yosefactory.runtime import turn

from .fake_adapter import FakeAdapter

FRAME = {"goal": "g", "method": "m", "assumptions": "a"}


def _seed_ready_item(repo: Path, item_id: str) -> Path:
    (repo / turn.ITEMS).mkdir(parents=True, exist_ok=True)
    path = repo / turn.ITEMS / f"{item_id}.jsonl"
    turn.append(path, backlog.ITEM, {"event": "created", "loop": "l", "frame": FRAME}, actor="denis")
    return path


def _seed_done_item(repo: Path, item_id: str) -> Path:
    path = _seed_ready_item(repo, item_id)
    turn.append(path, backlog.ITEM, {"event": "claimed", "owner": "o", "expires_at": "2099-01-01T00:00:00+00:00", "attempt": 1}, actor="o")
    turn.append(path, backlog.ITEM, {"event": "started"}, actor="o")
    turn.append(path, backlog.ITEM, {"event": "done", "effects": [], "verified_by": "test"}, actor="o")
    return path


def _seed_blocked_item(repo: Path, item_id: str, qid: str) -> Path:
    item_path = _seed_ready_item(repo, item_id)
    claim = {"event": "claimed", "owner": "o", "expires_at": "2099-01-01T00:00:00+00:00", "attempt": 1}
    turn.append(item_path, backlog.ITEM, claim, actor="o")
    turn.append(item_path, backlog.ITEM, {"event": "started"}, actor="o")
    awaiting = {"kind": "question", "ref": qid, "who": "denis", "since": "2026-08-17T00:00:00+00:00", "return_to": "doing", "nudge_at": []}
    turn.append(
        item_path,
        backlog.ITEM,
        {
            "event": "blocked",
            "awaiting": awaiting,
        },
        actor="o",
    )
    (repo / turn.QUESTIONS).mkdir(parents=True, exist_ok=True)
    q_path = repo / turn.QUESTIONS / f"{qid}.jsonl"
    turn.append(
        q_path,
        question.QUESTION,
        {
            "event": "asked",
            "item": item_id,
            "kind": "decision",
            "to": "denis",
            "text": "proceed?",
            "answer_type": "choice",
            "return_to": "doing",
            "deadline": "2099-01-01T00:00:00+00:00",
            "on_timeout": "escalate",
        },
        actor="o",
    )
    return item_path


def _event(event_id: str, type_: str, payload: dict, ts: str = "2026-08-17T00:00:00Z") -> Event:
    return Event(event_id=event_id, ts=ts, actor="denis", type=type_, payload=payload)


def test_set_priority_is_applied(tmp_path: Path) -> None:
    item_path = _seed_ready_item(tmp_path, "itm-a")
    adapter = FakeAdapter()
    adapter.queued_events = [_event("e1", "set_priority", {"priority": 7, "item_id": "itm-a", "ref": "1"})]

    results = ingest(tmp_path, adapter, actor="board")

    assert [r.result for r in results] == ["applied"]
    assert backlog.priority(backlog.load(item_path)) == 7


def test_cancel_is_applied(tmp_path: Path) -> None:
    item_path = _seed_ready_item(tmp_path, "itm-a")
    adapter = FakeAdapter()
    adapter.queued_events = [_event("e1", "cancel", {"reason": "wrong item", "item_id": "itm-a", "ref": "1"})]

    ingest(tmp_path, adapter, actor="board")

    assert backlog.load(item_path).state == "cancelled"


def test_answer_unblocks_via_apply_answers(tmp_path: Path) -> None:
    item_path = _seed_blocked_item(tmp_path, "itm-a", "q-1")
    adapter = FakeAdapter()
    adapter.queued_events = [_event("e1", "answer", {"answer": "yes", "item_id": "itm-a", "ref": "1"})]

    results = ingest(tmp_path, adapter, actor="board")
    assert [r.result for r in results] == ["applied"]

    moved = turn.apply_answers(tmp_path, actor="board")
    assert moved == ["itm-a"]
    assert backlog.load(item_path).state == "doing"


def test_rejection_is_visible_on_thread_and_does_not_raise(tmp_path: Path) -> None:
    _seed_done_item(tmp_path, "itm-done")
    adapter = FakeAdapter()
    ref = adapter.open(backlog.load(tmp_path / turn.ITEMS / "itm-done.jsonl"))
    adapter.queued_events = [_event("e1", "set_priority", {"priority": 9, "item_id": "itm-done", "ref": ref})]

    results = ingest(tmp_path, adapter, actor="board")

    assert results[0].result == "rejected"
    assert "illegal" in results[0].detail.lower() or "terminal" in results[0].detail.lower()
    assert adapter.threads[ref].comments  # a reply was posted on the same thread
    assert "rejected" in adapter.threads[ref].comments[0]


def test_unknown_item_is_rejected(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    adapter.queued_events = [_event("e1", "set_priority", {"priority": 1, "item_id": "itm-does-not-exist", "ref": None})]

    results = ingest(tmp_path, adapter, actor="board")

    assert results[0].result == "rejected"
    assert "not found" in results[0].detail


def test_one_rejection_does_not_block_the_rest_of_the_batch(tmp_path: Path) -> None:
    item_path = _seed_ready_item(tmp_path, "itm-a")
    adapter = FakeAdapter()
    adapter.queued_events = [
        _event("e1", "set_priority", {"priority": 1, "item_id": "itm-missing", "ref": None}, ts="2026-08-17T00:00:00Z"),
        _event("e2", "set_priority", {"priority": 5, "item_id": "itm-a", "ref": "1"}, ts="2026-08-17T00:00:01Z"),
    ]

    results = ingest(tmp_path, adapter, actor="board")

    assert {r.result for r in results} == {"rejected", "applied"}
    assert backlog.priority(backlog.load(item_path)) == 5


def test_idempotent_by_event_id(tmp_path: Path) -> None:
    item_path = _seed_ready_item(tmp_path, "itm-a")
    adapter = FakeAdapter()
    adapter.queued_events = [_event("e1", "set_priority", {"priority": 3, "item_id": "itm-a", "ref": "1"})]

    first = ingest(tmp_path, adapter, actor="board")
    second = ingest(tmp_path, adapter, actor="board")  # same event still "queued" (fake never drains)

    assert len(first) == 1
    assert len(second) == 0  # already consumed -- not re-applied
    lines = item_path.read_text(encoding="utf-8").splitlines()
    priority_lines = [line for line in lines if '"priority_set"' in line]
    assert len(priority_lines) == 1


def test_consumed_log_is_append_only_on_disk(tmp_path: Path) -> None:
    _seed_ready_item(tmp_path, "itm-a")
    adapter = FakeAdapter()
    adapter.queued_events = [_event("e1", "set_priority", {"priority": 1, "item_id": "itm-a", "ref": "1"})]

    ingest(tmp_path, adapter, actor="board")

    consumed_path = tmp_path / CONSUMED_LOG
    assert consumed_path.exists()
    lines = consumed_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
