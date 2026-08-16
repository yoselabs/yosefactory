"""Several rules for one event, tried in order — the fold's side of an absorbed race.

The property worth protecting is that absorption is *declared*. An event with no rule naming the
state it arrived in still fails the read, and the messages that failure produces are the format's
loudness in practice, so they are asserted verbatim.
"""

import json

import pytest

from yosefactory.protocol.eventlog import ANY, ANY_NON_TERMINAL, Declaration, LogError, Rule, loads

OPENED = {"event_id": "e1", "ts": "2026-08-18T09:00:00Z", "actor": "t", "event": "opened"}

TWO_RULES = Declaration(
    initial="opened",
    states=frozenset({"open", "closed"}),
    terminal=frozenset({"closed"}),
    rules={
        "opened": Rule(frozenset(), "open"),
        "closed": Rule(frozenset({"open"}), "closed", required=(("why",),)),
        "swept": (
            Rule(frozenset({"open"}), "closed", required=(("policy",),)),
            Rule(frozenset({"closed"}), None),
        ),
    },
)


def fold(declaration: Declaration, *records: dict):
    text = "\n".join(json.dumps(record) for record in records) + "\n"
    return loads(text, declaration, source="<inline>", log_id="log-test")


def event(name: str, **payload):
    number = payload.pop("n", 2)
    return {
        "event_id": f"e{number}",
        "ts": f"2026-08-18T09:0{number}:00Z",
        "actor": "t",
        "event": name,
        **payload,
    }


def test_the_first_matching_rule_wins() -> None:
    assert fold(TWO_RULES, OPENED, event("swept", policy="default")).state == "closed"


def test_a_later_rule_absorbs_what_the_first_could_not_take() -> None:
    folded = fold(TWO_RULES, OPENED, event("closed", why="by hand", n=2), event("swept", n=3))

    assert folded.state == "closed"
    assert [record["event"] for record in folded.records] == ["opened", "closed", "swept"]


def test_the_selected_rule_decides_the_payload_not_the_event_name() -> None:
    """The absorbing rule requires nothing; the transitioning one requires `policy`, in one log."""
    with pytest.raises(LogError, match=r"'swept' is missing required field 'policy'"):
        fold(TWO_RULES, OPENED, event("swept"))

    assert fold(TWO_RULES, OPENED, event("closed", why="x", n=2), event("swept", n=3)).state == "closed"


def test_an_event_no_rule_names_still_fails_from_a_terminal_state() -> None:
    with pytest.raises(LogError, match=r"'closed' is illegal from terminal state 'closed'"):
        fold(TWO_RULES, OPENED, event("closed", why="x", n=2), event("closed", why="again", n=3))


def test_a_non_terminal_mismatch_lists_every_state_the_event_is_legal_from() -> None:
    declaration = Declaration(
        initial="opened",
        states=frozenset({"open", "held", "closed"}),
        terminal=frozenset({"closed"}),
        rules={
            "opened": Rule(frozenset(), "open"),
            "held": Rule(frozenset({"open"}), "held"),
            "resumed": (Rule(frozenset({"held"}), "open"), Rule(frozenset({"closed"}), None)),
        },
    )

    with pytest.raises(LogError, match=r"'resumed' is illegal from state 'open'; legal from: closed, held"):
        fold(declaration, OPENED, event("resumed"))


def test_a_bare_rule_still_works_unchanged() -> None:
    single = Declaration(
        initial="opened",
        states=frozenset({"open", "closed"}),
        terminal=frozenset({"closed"}),
        rules={"opened": Rule(frozenset(), "open"), "closed": Rule(frozenset({"open"}), "closed")},
    )

    assert fold(single, OPENED, event("closed")).state == "closed"


def test_the_sentinels_keep_their_meaning() -> None:
    declaration = Declaration(
        initial="opened",
        states=frozenset({"open", "closed"}),
        terminal=frozenset({"closed"}),
        rules={
            "opened": Rule(frozenset(), "open"),
            "closed": Rule(frozenset({"open"}), "closed"),
            "noted": Rule(ANY, None),
            "touched": Rule(ANY_NON_TERMINAL, None),
        },
    )

    closed = fold(declaration, OPENED, event("closed", n=2), event("noted", n=3))
    assert closed.state == "closed"

    with pytest.raises(LogError, match=r"'touched' is illegal from terminal state 'closed'"):
        fold(declaration, OPENED, event("closed", n=2), event("touched", n=3))
