"""There is no blocked state, only blocked *until* — architecture.md §5.

Starvation is the failure this design says bites, and `on_timeout` is the field every mature tracker
forgets and then implements as policy. What changed is *where* the until is stored, not whether it
exists: a block on a question reads it from the question, which owns it, and a block on another item
carries it itself, because nothing else can. The duplication argument applies only where the fact has
another home.
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

# A block on a question names it and stops there. The deadline lives on the question.
AWAITING = {
    "kind": "question",
    "ref": "q-0004",
    "who": "denis",
    "since": "2026-08-14T09:03:00Z",
    "return_to": "doing",
    "nudge_at": ["2026-08-17T09:03:00Z", "2026-08-21T09:03:00Z"],
}
# A block on another item has no question to read from, so the bound is here or nowhere.
AWAITING_ITEM = {
    **AWAITING,
    "kind": "item",
    "ref": "itm-0009",
    "who": "loop:a2web",
    "deadline": "2026-08-24T09:03:00Z",
    "on_timeout": "escalate",
}
BLOCKED = {"event_id": "e4", "ts": "2026-08-14T09:03:00Z", "actor": "t1", "event": "blocked", "awaiting": AWAITING}
BLOCKED_ON_ITEM = {**BLOCKED, "awaiting": AWAITING_ITEM}


def fold(*records: dict):
    return loads("\n".join(json.dumps(record) for record in records) + "\n", backlog.ITEM, source="<inline>", log_id="itm-test")


def test_a_block_on_a_question_carries_no_deadline_of_its_own() -> None:
    """The question owns the closure; a copy here would be the one that drifts."""
    item = fold(CREATED, CLAIMED, STARTED, BLOCKED)

    assert item.state == "blocked"
    block = backlog.awaiting(item)
    assert block is not None
    assert block["ref"] == "q-0004"
    assert "deadline" not in block
    assert "on_timeout" not in block


def test_a_block_on_another_item_carries_its_own_bound() -> None:
    """No question exists to hold it, so removing it here would let the block hang forever (S172)."""
    item = fold(CREATED, CLAIMED, STARTED, BLOCKED_ON_ITEM)

    block = backlog.awaiting(item)
    assert block is not None
    assert block["deadline"] == "2026-08-24T09:03:00Z"
    assert block["on_timeout"] == "escalate"


def test_an_unrecognised_on_timeout_fails_the_read() -> None:
    """Checked wherever it appears: patterns skip an absent field and validate a present one."""
    nonsense = {**BLOCKED_ON_ITEM, "awaiting": {**AWAITING_ITEM, "on_timeout": "wait"}}

    with pytest.raises(LogError, match=r"awaiting\.on_timeout is 'wait'"):
        fold(CREATED, CLAIMED, STARTED, nonsense)


@pytest.mark.parametrize("on_timeout", ["escalate", "default:use the 30s ceiling", "abandon:origin was retired"])
def test_the_three_pre_registered_outcomes_are_legal(on_timeout: str) -> None:
    blocked = {**BLOCKED_ON_ITEM, "awaiting": {**AWAITING_ITEM, "on_timeout": on_timeout}}

    item = fold(CREATED, CLAIMED, STARTED, blocked)

    assert item.state == "blocked"
    assert backlog.awaiting(item) is not None
    assert backlog.awaiting(item)["on_timeout"] == on_timeout


def test_an_answer_returns_the_item_to_the_state_stored_at_block_time() -> None:
    answered = {
        "event_id": "e5",
        "ts": "2026-08-15T11:00:00Z",
        "actor": "denis",
        "event": "unblocked",
        "resolution": "answered",
        "ref": "q-0004",
    }

    item = fold(CREATED, CLAIMED, STARTED, BLOCKED, answered)

    assert item.state == "doing"
    assert backlog.awaiting(item) is None


def test_a_deadline_firing_returns_the_item_to_the_same_stored_state() -> None:
    timed_out = {
        "event_id": "e5",
        "ts": "2026-08-24T09:03:01Z",
        "actor": "sweeper",
        "event": "unblocked",
        "resolution": "timeout",
        "ref": "q-0004",
    }

    assert fold(CREATED, CLAIMED, STARTED, BLOCKED, timed_out).state == "doing"


def test_return_to_is_read_from_the_block_not_recomputed() -> None:
    """A block written from `claimed` returns to `claimed`, even though the last work state was `doing`."""
    released = {
        "event_id": "e4",
        "ts": "2026-08-14T09:03:00Z",
        "actor": "t1",
        "event": "released",
        "owner": "t1",
        "reason": "lease expired",
    }
    reclaimed = {**CLAIMED, "event_id": "e5", "ts": "2026-08-14T09:04:00Z", "attempt": 2}
    blocked_from_claimed = {
        "event_id": "e6",
        "ts": "2026-08-14T09:05:00Z",
        "actor": "t1",
        "event": "blocked",
        "awaiting": {**AWAITING, "return_to": "claimed"},
    }
    answered = {
        "event_id": "e7",
        "ts": "2026-08-15T11:00:00Z",
        "actor": "denis",
        "event": "unblocked",
        "resolution": "answered",
        "ref": "q-0004",
    }

    item = fold(CREATED, CLAIMED, STARTED, released, reclaimed, blocked_from_claimed, answered)

    assert item.state == "claimed"
    assert backlog.lease(item) is not None
    assert backlog.lease(item)["attempt"] == 2


def test_a_snoozed_item_wakes_ready() -> None:
    snoozed = {
        "event_id": "e2s",
        "ts": "2026-08-14T09:00:30Z",
        "actor": "denis",
        "event": "snoozed",
        "scheduled_for": "2026-08-20T09:00:00Z",
    }
    woke = {"event_id": "e3s", "ts": "2026-08-20T09:00:01Z", "actor": "sweeper", "event": "woke", "cause": "timer"}

    assert fold(CREATED, snoozed, woke).state == "ready"
