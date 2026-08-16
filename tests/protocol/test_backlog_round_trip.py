"""The acceptance criterion for the backlog item format, written before the format could be read.

A falsified item and its successor round-trip: the closed item stays readable, the successor names
what falsified its predecessor, and neither operation loses information. Everything else in this
capability is machinery in service of this test.
"""

from pathlib import Path

from yosefactory.protocol import backlog

FIXTURES = Path(__file__).resolve().parents[2] / "backlog" / "fixtures" / "falsified-round-trip"


def test_falsified_item_stays_readable() -> None:
    item = backlog.load(FIXTURES / "itm-0007.jsonl")

    assert item.state == "falsified"
    assert item.terminal is False

    frame = backlog.frame(item)
    assert frame["goal"] == "Cut a2web cold-start fetch latency below 400ms"
    assert frame["method"].startswith("Cache the parsed dom-schema per host")
    assert frame["assumptions"] == [
        "Parsing dominates cold-start cost",
        "A per-host schema is stable enough to reuse within one session",
    ]

    assert [record["event"] for record in item.records] == ["created", "claimed", "started", "note", "falsified"]


def test_falsification_carries_its_evidence_in_the_log() -> None:
    item = backlog.load(FIXTURES / "itm-0007.jsonl")
    falsification = backlog.falsification(item)

    assert falsification is not None
    assert "38ms" in falsification["by"]
    assert falsification["by"].endswith("Caching the parsed schema cannot move the number this item exists to move.")


def test_successor_names_what_falsified_its_predecessor() -> None:
    successor = backlog.load(FIXTURES / "itm-0011.jsonl")

    assert successor.state == "ready"
    assert backlog.predecessor(successor) == "itm-0007"

    frame = backlog.frame(successor)
    assert frame["goal"] == "Cut a2web cold-start fetch latency below 400ms"
    assert frame["method"] != backlog.frame(backlog.load(FIXTURES / "itm-0007.jsonl"))["method"]
    assert any("itm-0007 was falsified" in assumption for assumption in frame["assumptions"])


def test_the_link_round_trips_in_both_directions() -> None:
    item = backlog.load(FIXTURES / "itm-0007.jsonl")

    forward = backlog.successor(item)
    assert forward == "itm-0011"

    successor = backlog.load(FIXTURES / f"{forward}.jsonl")
    assert backlog.predecessor(successor) == item.id


def test_nothing_present_before_the_falsification_is_absent_after() -> None:
    """The falsified item is closed by appending, never by rewriting — so its first line is intact."""
    item = backlog.load(FIXTURES / "itm-0007.jsonl")
    created = item.records[0]

    assert created["loop"] == "a2web"
    assert created["actor"] == "denis"
    assert created["ts"] == "2026-08-14T09:02:00Z"
    assert set(created["frame"]) == {"goal", "method", "assumptions"}
