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


def test_claims_counts_the_whole_history_not_just_the_current_lease() -> None:
    """`lease()` reads `None` once an item is back to `ready` (`released` or `reclaimed`), so a
    claim-attempt computation keyed off it alone always restarts at zero -- unstick-the-backlog /
    S1021 found `take_turn`'s own claim step doing exactly that, meaning `attempt` could never
    exceed 1 in production. `claims()` counts every `claimed` event ever appended instead."""
    released = {"event_id": "e4", "ts": "2026-08-14T09:05:00Z", "actor": "t1", "event": "released", "owner": "t1", "reason": "r"}
    reclaimed_second_lease = {
        "event_id": "e6",
        "ts": "2026-08-14T09:07:00Z",
        "actor": "t2",
        "event": "claimed",
        "owner": "t2",
        "expires_at": "2026-08-14T09:37:00Z",
        "attempt": 2,
    }

    once = fold(CREATED, CLAIMED, STARTED, released)
    assert backlog.claims(once) == 1
    assert backlog.lease(once) is None  # back to `ready` -- lease() alone would read this as zero

    twice = fold(CREATED, CLAIMED, STARTED, released, reclaimed_second_lease)
    assert backlog.claims(twice) == 2


def test_a_reclaimed_item_returns_to_ready_and_names_the_expired_lease() -> None:
    reclaimed = {
        "event_id": "e4",
        "ts": "2026-08-14T09:35:00Z",
        "actor": "sweep",
        "event": "reclaimed",
        "reason": "lease expired",
        "expired_owner": "t1",
        "expired_attempt": 1,
    }
    item = fold(CREATED, CLAIMED, STARTED, reclaimed)
    assert item.state == "ready"


def test_reclaimed_is_illegal_from_ready() -> None:
    reclaimed = {
        "event_id": "e2",
        "ts": "2026-08-14T09:01:00Z",
        "actor": "sweep",
        "event": "reclaimed",
        "reason": "lease expired",
        "expired_owner": "t1",
        "expired_attempt": 1,
    }
    with pytest.raises(LogError, match="'reclaimed' is illegal from state 'ready'"):
        fold(CREATED, reclaimed)


def test_reclaimed_requires_its_three_fields() -> None:
    incomplete = {
        "event_id": "e4",
        "ts": "2026-08-14T09:35:00Z",
        "actor": "sweep",
        "event": "reclaimed",
        "reason": "lease expired",
    }
    with pytest.raises(LogError):
        fold(CREATED, CLAIMED, STARTED, incomplete)


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


def _documented_carries() -> dict[str, set[str]]:
    """Parses the event table's own `Carries` column, live from the file `VOCABULARY_SPEC` points
    an agent at -- not a copy pasted into this test, which could drift from the file without
    anyone noticing."""
    section = backlog.VOCABULARY_SPEC.read_text(encoding="utf-8").split(
        "### Requirement: The event vocabulary and its transitions", 1
    )[1]
    lines = section.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith("| Event"))
    documented: dict[str, set[str]] = {}
    for line in lines[start:]:
        line = line.strip()
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        event = cells[0].strip("`")
        if event == "Event" or set(event) <= {"-"}:
            continue
        carries = cells[3]
        documented[event] = {name.strip().strip("`") for name in carries.split(",") if name.strip() and name.strip() != "—"}
    return documented


def test_the_vocabulary_table_promises_at_least_what_the_fold_requires() -> None:
    """The content half of `teach-the-done-event-schema`'s drift guard: if a future change
    tightens `ITEM.rules`' required fields without updating the table an agent is pointed at
    (`Invocation.vocabulary`), this fails. Subset, not equality -- the table also documents
    non-required context (`unblocked`'s `ref` is listed but not enforced, pre-existing and
    correct); what must never happen is the fold requiring a field the table never mentions,
    which is the exact shape of gap that made the original `done` proposal illegible."""
    documented = _documented_carries()

    for event, rule_or_rules in backlog.ITEM.rules.items():
        assert event in documented, f"{event!r} is not in the vocabulary table"
        rules = rule_or_rules if isinstance(rule_or_rules, tuple) else (rule_or_rules,)
        for rule in rules:
            required_top_level = {path[0] for path in rule.required}
            missing = required_top_level - documented[event]
            assert not missing, f"{event!r} requires {missing} but the table's Carries cell doesn't mention it"
