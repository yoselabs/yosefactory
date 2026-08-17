from __future__ import annotations

import pytest

from yosefactory.board.event import Event, parse_command


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/priority 5", ("set_priority", {"priority": 5})),
        ("/priority -1", ("set_priority", {"priority": -1})),
        ("  /priority 2  ", ("set_priority", {"priority": 2})),
        ("/answer yes please", ("answer", {"answer": "yes please"})),
        ("/cancel not needed anymore", ("cancel", {"reason": "not needed anymore"})),
    ],
)
def test_parse_command_recognized(text: str, expected: tuple[str, dict]) -> None:
    assert parse_command(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "just a note, not a command",
        "/priority high",
        "/prioritize 5",
        "/",
        "",
        "not / at the start /priority 5",
    ],
)
def test_parse_command_not_recognized(text: str) -> None:
    assert parse_command(text) is None


def test_event_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="not one of"):
        Event(event_id="e1", ts="2026-08-17T00:00:00Z", actor="denis", type="delete_everything", payload={})
