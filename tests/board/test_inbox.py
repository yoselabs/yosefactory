from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from yosefactory.board.event import Event
from yosefactory.board.inbox import CONSUMED_LOG, ingest
from yosefactory.protocol import backlog, question
from yosefactory.runtime import turn

from .fake_adapter import FakeAdapter, Thread

FRAME = {"goal": "g", "method": "m", "assumptions": "a"}


def git(target: Path, *args: str) -> str:
    binary = shutil.which("git")
    assert binary is not None
    completed = subprocess.run([binary, *args], cwd=target, capture_output=True, text=True, check=True)  # noqa: S603
    return completed.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real git repo -- `ingest()` now commits what it applies (this change's own fix), so a
    bare directory no longer exercises the code path these tests are for."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.invalid")
    git(root, "config", "user.name", "T")
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(root, "add", "seed.txt")
    git(root, "commit", "-q", "-m", "seed")
    return root


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


def test_set_priority_is_applied(repo: Path) -> None:
    item_path = _seed_ready_item(repo, "itm-a")
    adapter = FakeAdapter()
    adapter.queued_events = [_event("e1", "set_priority", {"priority": 7, "item_id": "itm-a", "ref": "1"})]

    results = ingest(repo, adapter, actor="board")

    assert [r.result for r in results] == ["applied"]
    assert backlog.priority(backlog.load(item_path)) == 7


def test_cancel_is_applied(repo: Path) -> None:
    item_path = _seed_ready_item(repo, "itm-a")
    adapter = FakeAdapter()
    adapter.queued_events = [_event("e1", "cancel", {"reason": "wrong item", "item_id": "itm-a", "ref": "1"})]

    ingest(repo, adapter, actor="board")

    assert backlog.load(item_path).state == "cancelled"


def test_answer_unblocks_via_apply_answers(repo: Path) -> None:
    item_path = _seed_blocked_item(repo, "itm-a", "q-1")
    adapter = FakeAdapter()
    adapter.queued_events = [_event("e1", "answer", {"answer": "yes", "item_id": "itm-a", "ref": "1"})]

    results = ingest(repo, adapter, actor="board")
    assert [r.result for r in results] == ["applied"]

    moved = turn.apply_answers(repo, actor="board")
    assert moved == ["itm-a"]
    assert backlog.load(item_path).state == "doing"


def test_rejection_is_visible_on_thread_and_does_not_raise(repo: Path) -> None:
    _seed_done_item(repo, "itm-done")
    adapter = FakeAdapter()
    ref = adapter.open(backlog.load(repo / turn.ITEMS / "itm-done.jsonl"))
    adapter.queued_events = [_event("e1", "set_priority", {"priority": 9, "item_id": "itm-done", "ref": ref})]

    results = ingest(repo, adapter, actor="board")

    assert results[0].result == "rejected"
    assert "illegal" in results[0].detail.lower() or "terminal" in results[0].detail.lower()
    assert adapter.threads[ref].comments  # a reply was posted on the same thread
    assert "rejected" in adapter.threads[ref].comments[0]


def test_unknown_item_is_rejected(repo: Path) -> None:
    adapter = FakeAdapter()
    adapter.queued_events = [_event("e1", "set_priority", {"priority": 1, "item_id": "itm-does-not-exist", "ref": None})]

    results = ingest(repo, adapter, actor="board")

    assert results[0].result == "rejected"
    assert "not found" in results[0].detail


def test_one_rejection_does_not_block_the_rest_of_the_batch(repo: Path) -> None:
    item_path = _seed_ready_item(repo, "itm-a")
    adapter = FakeAdapter()
    adapter.queued_events = [
        _event("e1", "set_priority", {"priority": 1, "item_id": "itm-missing", "ref": None}, ts="2026-08-17T00:00:00Z"),
        _event("e2", "set_priority", {"priority": 5, "item_id": "itm-a", "ref": "1"}, ts="2026-08-17T00:00:01Z"),
    ]

    results = ingest(repo, adapter, actor="board")

    assert {r.result for r in results} == {"rejected", "applied"}
    assert backlog.priority(backlog.load(item_path)) == 5


def test_idempotent_by_event_id(repo: Path) -> None:
    item_path = _seed_ready_item(repo, "itm-a")
    adapter = FakeAdapter()
    adapter.queued_events = [_event("e1", "set_priority", {"priority": 3, "item_id": "itm-a", "ref": "1"})]

    first = ingest(repo, adapter, actor="board")
    second = ingest(repo, adapter, actor="board")  # same event still "queued" (fake never drains)

    assert len(first) == 1
    assert len(second) == 0  # already consumed -- not re-applied
    lines = item_path.read_text(encoding="utf-8").splitlines()
    priority_lines = [line for line in lines if '"priority_set"' in line]
    assert len(priority_lines) == 1


def test_applied_command_is_a_real_commit(repo: Path) -> None:
    """board-projection/inbox: "a command's effect is committed to git, not left in the working
    tree" -- checked from `git log`/`git status`, not from the file content alone."""
    _seed_ready_item(repo, "itm-a")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed item")
    before = git(repo, "rev-parse", "HEAD")

    adapter = FakeAdapter()
    adapter.queued_events = [_event("e1", "set_priority", {"priority": 7, "item_id": "itm-a", "ref": "1"})]
    ingest(repo, adapter, actor="board")

    after = git(repo, "rev-parse", "HEAD")
    assert after != before  # a new commit landed
    assert git(repo, "status", "--porcelain") == ""  # nothing left uncommitted
    log = git(repo, "log", "-1", "--format=%s")
    assert "board(e1)" in log
    assert "set_priority" in log


def test_rejected_command_still_commits_the_consumed_log(repo: Path) -> None:
    adapter = FakeAdapter()
    adapter.queued_events = [_event("e1", "set_priority", {"priority": 1, "item_id": "itm-missing", "ref": None})]
    before = git(repo, "rev-parse", "HEAD")

    ingest(repo, adapter, actor="board")

    after = git(repo, "rev-parse", "HEAD")
    assert after != before
    assert git(repo, "status", "--porcelain") == ""


def test_consumed_log_is_append_only_on_disk(repo: Path) -> None:
    _seed_ready_item(repo, "itm-a")
    adapter = FakeAdapter()
    adapter.queued_events = [_event("e1", "set_priority", {"priority": 1, "item_id": "itm-a", "ref": "1"})]

    ingest(repo, adapter, actor="board")

    consumed_path = repo / CONSUMED_LOG
    assert consumed_path.exists()
    lines = consumed_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


# -- create (D031, open-issue-becomes-backlog-item) --------------------------------------------


def test_create_command_makes_a_new_item_with_a_degenerate_frame(repo: Path) -> None:
    adapter = FakeAdapter()
    adapter.threads["1"] = Thread(item_id="")  # the pre-existing, not-yet-ingested issue
    payload = {"title": "fix the flaky login test", "body": "it fails on CI about 1/10 runs", "ref": "1"}
    adapter.queued_events = [_event("e1", "create", payload)]

    results = ingest(repo, adapter, actor="board")

    assert [r.result for r in results] == ["applied"]
    item_id = results[0].item_id
    assert item_id is not None
    item = backlog.load(repo / turn.ITEMS / f"{item_id}.jsonl")
    assert item.state == "ready"
    frame = backlog.frame(item)
    assert frame["goal"] == "fix the flaky login test"
    assert frame["method"] == "it fails on CI about 1/10 runs"
    assert frame["assumptions"]  # non-empty; degenerate but present
    assert item.records[0]["loop"] == "board-intake"


def test_create_from_a_thin_issue_still_produces_a_legal_frame(repo: Path) -> None:
    """design.md's thin-issue choice: an empty body is filled with a placeholder, not refused
    and not blocked -- this is the motivating scenario (a one-line issue dictated by phone)."""
    adapter = FakeAdapter()
    adapter.threads["1"] = Thread(item_id="")
    adapter.queued_events = [_event("e1", "create", {"title": "wifi keeps dropping", "body": "", "ref": "1"})]

    results = ingest(repo, adapter, actor="board")

    assert [r.result for r in results] == ["applied"]
    item = backlog.load(repo / turn.ITEMS / f"{results[0].item_id}.jsonl")
    assert item.state == "ready"
    frame = backlog.frame(item)
    assert frame["method"]  # a placeholder, not empty -- backlog.ITEM's `created` rule requires it


def test_create_stamps_the_marker_back_onto_the_source_thread(repo: Path) -> None:
    """Structural idempotence (design.md): the same call that creates the item projects it back
    onto the thread it came from, before ingest() returns."""
    adapter = FakeAdapter()
    adapter.threads["1"] = Thread(item_id="")
    adapter.queued_events = [_event("e1", "create", {"title": "g", "body": "m", "ref": "1"})]

    results = ingest(repo, adapter, actor="board")

    thread = adapter.threads["1"]
    assert thread.title  # project() wrote something derived from the new item
    assert thread.state == "ready"
    assert results[0].result == "applied"


def test_rejected_create_leaves_no_item_file_and_is_visible_on_the_thread(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = FakeAdapter()
    adapter.threads["1"] = Thread(item_id="")
    adapter.queued_events = [_event("e1", "create", {"title": "g", "body": "m", "ref": "1"})]

    def _boom(*_args: object, **_kwargs: object) -> None:
        from yosefactory.protocol.eventlog import LogError

        raise LogError("forced failure", source="test")

    from yosefactory.board import inbox as inbox_module

    monkeypatch.setattr(inbox_module, "turn_append", _boom)

    results = ingest(repo, adapter, actor="board")

    assert results[0].result == "rejected"
    assert not list((repo / turn.ITEMS).glob("*.jsonl"))  # no item file was left behind
    assert adapter.threads["1"].comments
    assert "rejected" in adapter.threads["1"].comments[0]


def test_create_is_idempotent_by_event_id(repo: Path) -> None:
    adapter = FakeAdapter()
    adapter.threads["1"] = Thread(item_id="")
    adapter.queued_events = [_event("e1", "create", {"title": "g", "body": "m", "ref": "1"})]

    first = ingest(repo, adapter, actor="board")
    second = ingest(repo, adapter, actor="board")  # same event still "queued" (fake never drains)

    assert len(first) == 1
    assert len(second) == 0  # already consumed -- not re-created
    assert len(list((repo / turn.ITEMS).glob("*.jsonl"))) == 1
