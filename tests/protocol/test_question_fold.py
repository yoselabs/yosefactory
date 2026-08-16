"""The question declaration, run against the fixtures that claim what it does.

These fixtures were checked once from a scratch script and the claim then rotted: the declaration
snippet in `questions/examples/README.md` scoped `noted` to `awaiting` while the spec made it legal
from any state. This file exists so the claim is executed rather than asserted in prose.
"""

import json
from pathlib import Path

import pytest

from yosefactory.protocol import question
from yosefactory.protocol.eventlog import LogError, loads

EXAMPLES = Path(__file__).resolve().parents[2] / "questions" / "examples"

# Each fixture and the state its README row claims.
CLAIMED = {
    "q-20260816T171204Z-3f9a2c1d": "answered",
    "q-20260816T171331Z-b7e40a52": "awaiting",
    "q-20260816T171402Z-5c1de9f7": "timed_out",
    "q-20260817T080200Z-9ab35e04": "answered",
    "q-20260818T164500Z-d41c8e37": "answered",
}

ASKED = {
    "event": "asked",
    "event_id": "ask-1",
    "qid": "q-test",
    "ts": "2026-08-18T09:00:00Z",
    "actor": "loop:yosefactory/turn",
    "item": "i-1",
    "kind": "decision",
    "to": "denis",
    "text": "?",
    "answer_type": "bool",
    "return_to": "doing",
    "deadline": "2026-08-19T09:00:00Z",
    "on_timeout": "default:false",
}
ANSWERED = {
    "event": "answered",
    "event_id": "answer-1",
    "qid": "q-test",
    "ts": "2026-08-18T10:00:00Z",
    "actor": "denis",
    "verdict": "accept",
    "answer": True,
}


def fold(*records: dict):
    text = "\n".join(json.dumps(record) for record in records) + "\n"
    return loads(text, question.QUESTION, source="<inline>", log_id="q-test")


def test_every_fixture_is_covered_by_this_test() -> None:
    on_disk = {path.stem for path in EXAMPLES.glob("*.jsonl")}

    assert on_disk == set(CLAIMED), "a fixture was added or removed without updating CLAIMED"


@pytest.mark.parametrize(("stem", "state"), sorted(CLAIMED.items()))
def test_a_fixture_folds_to_the_state_its_readme_row_claims(stem: str, state: str) -> None:
    folded = question.load(EXAMPLES / f"{stem}.jsonl")

    assert folded.state == state
    assert folded.terminal is (state in question.TERMINAL)


def test_answering_one_question_leaves_its_sibling_awaiting() -> None:
    """The acceptance test the format was dispatched with, read off the fixtures rather than argued."""
    answered = question.load(EXAMPLES / "q-20260816T171204Z-3f9a2c1d.jsonl")
    sibling = question.load(EXAMPLES / "q-20260816T171331Z-b7e40a52.jsonl")

    assert answered.state == "answered"
    assert sibling.state == "awaiting"


def test_a_sweeper_that_lost_the_race_is_absorbed_and_kept() -> None:
    folded = question.load(EXAMPLES / "q-20260818T164500Z-d41c8e37.jsonl")

    assert folded.state == "answered"
    assert question.outcome(folded)["actor"] == "denis"
    absorbed = question.absorbed(folded)
    assert [record["event"] for record in absorbed] == ["timed_out"]
    assert absorbed[0]["actor"] == "loop:yosefactory/sweeper"


def test_a_late_timeout_needs_no_payload_because_it_changes_nothing() -> None:
    bare = {
        "event": "timed_out",
        "event_id": "sweep-1",
        "qid": "q-test",
        "ts": "2026-08-19T09:00:01Z",
        "actor": "loop:yosefactory/sweeper",
    }

    assert fold(ASKED, ANSWERED, bare).state == "answered"


def test_a_timeout_that_wins_the_race_must_still_carry_its_policy() -> None:
    bare = {
        "event": "timed_out",
        "event_id": "sweep-1",
        "qid": "q-test",
        "ts": "2026-08-19T09:00:01Z",
        "actor": "loop:yosefactory/sweeper",
    }

    with pytest.raises(LogError, match=r"'timed_out' is missing required field 'policy'"):
        fold(ASKED, bare)


def test_a_second_answer_under_a_different_event_id_still_fails() -> None:
    again = {**ANSWERED, "event_id": "answer-2", "ts": "2026-08-18T11:00:00Z", "answer": False}

    with pytest.raises(LogError, match=r"'answered' is illegal from terminal state 'answered'"):
        fold(ASKED, ANSWERED, again)


def test_cancelling_an_answered_question_fails_because_a_canceller_could_have_read_the_log() -> None:
    cancelled = {
        "event": "cancelled",
        "event_id": "cancel-1",
        "qid": "q-test",
        "ts": "2026-08-18T10:00:01Z",
        "actor": "denis",
        "reason": "changed my mind",
    }

    with pytest.raises(LogError, match=r"'cancelled' is illegal from terminal state 'answered'"):
        fold(ASKED, ANSWERED, cancelled)


def test_a_note_after_closing_is_legal_and_changes_nothing() -> None:
    noted = {
        "event": "noted",
        "event_id": "note-1",
        "qid": "q-test",
        "ts": "2026-08-20T09:00:00Z",
        "actor": "denis",
        "body": "the answer held up",
    }

    folded = fold(ASKED, ANSWERED, noted)

    assert folded.state == "answered"
    assert folded.records[-1]["event"] == "noted"


def test_a_kind_outside_the_closed_set_fails_the_read() -> None:
    with pytest.raises(LogError, match=r"kind is 'urgent'"):
        fold({**ASKED, "kind": "urgent"})


def test_a_question_that_could_never_close_fails_the_read() -> None:
    for field in ("deadline", "on_timeout"):
        with pytest.raises(LogError, match=rf"'asked' is missing required field '{field}'"):
            fold({key: value for key, value in ASKED.items() if key != field})


def test_the_question_owns_its_closure() -> None:
    folded = fold(ASKED)

    assert question.deadline(folded) == "2026-08-19T09:00:00Z"
    assert question.on_timeout(folded) == "default:false"
    assert question.blocking_by_design(folded) is False
