"""The rest of the capability's scenarios: order, duplication, loudness, and blocked-until.

Logs are written inline here rather than as fixtures — these are properties of the fold, and a
property is clearest next to the lines that violate it.
"""

import json

import pytest

from yosefactory.protocol import backlog
from yosefactory.protocol.eventlog import LogError, loads

CREATED = {
    "event_id": "e1",
    "ts": "2026-08-14T09:00:00Z",
    "actor": "denis",
    "event": "created",
    "loop": "a2web",
    "frame": {"goal": "g", "method": "m", "assumptions": []},
}
CLAIMED = {
    "event_id": "e2",
    "ts": "2026-08-14T09:01:00Z",
    "actor": "t1",
    "event": "claimed",
    "owner": "t1",
    "expires_at": "2026-08-14T09:31:00Z",
    "attempt": 1,
}
STARTED = {"event_id": "e3", "ts": "2026-08-14T09:02:00Z", "actor": "t1", "event": "started"}


def log(*records: dict) -> str:
    return "\n".join(json.dumps(record) for record in records) + "\n"


def fold(*records: dict):
    return loads(log(*records), backlog.ITEM, source="<inline>", log_id="itm-test")


def test_file_order_does_not_change_the_fold() -> None:
    forwards = fold(CREATED, CLAIMED, STARTED)
    backwards = loads(log(STARTED, CLAIMED, CREATED), backlog.ITEM, source="<inline>", log_id="itm-test")

    assert forwards.state == backwards.state == "doing"
    assert [record["event_id"] for record in forwards.records] == [record["event_id"] for record in backwards.records]


def test_a_duplicated_line_applies_once() -> None:
    item = fold(CREATED, CLAIMED, CLAIMED, STARTED)

    assert item.state == "doing"
    assert [record["event_id"] for record in item.records] == ["e1", "e2", "e3"]


def test_one_event_id_with_two_bodies_is_corruption() -> None:
    impostor = dict(CLAIMED, owner="t2")

    with pytest.raises(LogError, match="appears twice with different content"):
        fold(CREATED, CLAIMED, impostor)


def test_an_unknown_event_is_not_skipped() -> None:
    archived = {"event_id": "e9", "ts": "2026-08-14T09:03:00Z", "actor": "t1", "event": "archived"}

    with pytest.raises(LogError, match="unknown event 'archived'"):
        fold(CREATED, CLAIMED, STARTED, archived)


def test_a_malformed_line_names_its_line_number() -> None:
    text = log(CREATED) + "{not json}\n"

    with pytest.raises(LogError, match="<inline>:2: not valid JSON"):
        loads(text, backlog.ITEM, source="<inline>", log_id="itm-test")


def test_a_line_missing_a_required_field_fails_the_read() -> None:
    headless = {"event_id": "e4", "ts": "2026-08-14T09:03:00Z", "event": "started"}

    with pytest.raises(LogError, match="missing required field\\(s\\): actor"):
        loads(log(CREATED, CLAIMED, headless), backlog.ITEM, source="<inline>", log_id="itm-test")


def test_an_illegal_transition_names_both_states() -> None:
    with pytest.raises(LogError, match="'started' is illegal from state 'ready'"):
        fold(CREATED, STARTED)


def test_writing_after_a_terminal_state_is_rejected() -> None:
    cancelled = {"event_id": "e4", "ts": "2026-08-14T09:04:00Z", "actor": "denis", "event": "cancelled", "reason": "superseded"}

    with pytest.raises(LogError, match="illegal from terminal state 'cancelled'"):
        fold(CREATED, CLAIMED, STARTED, cancelled, dict(CLAIMED, event_id="e5", ts="2026-08-14T09:05:00Z"))


def test_a_note_is_legal_after_a_terminal_state() -> None:
    cancelled = {"event_id": "e4", "ts": "2026-08-14T09:04:00Z", "actor": "denis", "event": "cancelled", "reason": "superseded"}
    note = {"event_id": "e5", "ts": "2026-08-14T09:06:00Z", "actor": "denis", "event": "note", "body": "closed by hand on the board"}

    item = fold(CREATED, CLAIMED, STARTED, cancelled, note)

    assert item.state == "cancelled"
    assert item.terminal is True


def test_an_infrastructure_error_is_failed_not_falsified() -> None:
    failed = {
        "event_id": "e4",
        "ts": "2026-08-14T09:05:00Z",
        "actor": "t1",
        "event": "failed",
        "reason": "origin returned HTTP 500 on the third retry",
        "attempt": 1,
        "retryable": True,
    }

    item = fold(CREATED, CLAIMED, STARTED, failed)

    assert item.state == "failed"
    assert item.terminal is False
    assert backlog.successor(item) is None


def test_a_poisoned_item_is_terminal_and_only_reachable_from_failed() -> None:
    failed = {
        "event_id": "e4",
        "ts": "2026-08-14T09:05:00Z",
        "actor": "t1",
        "event": "failed",
        "reason": "boom",
        "attempt": 3,
        "retryable": False,
    }
    poisoned = {"event_id": "e5", "ts": "2026-08-14T09:06:00Z", "actor": "t1", "event": "poisoned", "attempts": 3}

    assert fold(CREATED, CLAIMED, STARTED, failed, poisoned).state == "poison"

    with pytest.raises(LogError, match="'poisoned' is illegal from state 'doing'"):
        fold(CREATED, CLAIMED, STARTED, poisoned)


def test_closing_a_duplicate_names_a_survivor_and_touches_nothing_else() -> None:
    duplicate = {"event_id": "e4", "ts": "2026-08-14T09:05:00Z", "actor": "t1", "event": "duplicate", "survivor": "itm-0002"}
    closed = fold(CREATED, CLAIMED, STARTED, duplicate)
    survivor_log = loads(log(CREATED), backlog.ITEM, source="<inline>", log_id="itm-0002")

    assert closed.state == "duplicate"
    assert backlog.survivor(closed) == "itm-0002"
    assert len(survivor_log.records) == 1


def test_a_frame_amendment_keeps_the_original_readable() -> None:
    amended = {
        "event_id": "e4",
        "ts": "2026-08-14T09:05:00Z",
        "actor": "denis",
        "event": "frame_amended",
        "frame": {"method": "hold a warm connection pool per host"},
    }

    item = fold(CREATED, CLAIMED, STARTED, amended)

    assert backlog.frame(item)["method"] == "hold a warm connection pool per host"
    assert backlog.frame(item)["goal"] == "g"
    assert item.records[0]["frame"]["method"] == "m"
    assert item.state == "doing"
