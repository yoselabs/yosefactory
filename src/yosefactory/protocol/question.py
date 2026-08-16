"""The question's declaration: four states, six events, and the one event that absorbs a lost race.

Data plus small readers, like `backlog`. The fold lives in `eventlog` and knows nothing about
questions — D020 makes a request, a question and a work item one object in different states, so a
second parser here would be a modelling error rather than a convenience.

`timed_out` carries two rules. From `awaiting` it closes the question; from a state that is already
terminal it changes nothing and the record is kept. That is not tolerance in general: a sweeper reads
the log and appends as two steps and cannot fuse them, so a close landing a second after Denis's own
answer is a race it could not have avoided. `answered` and `cancelled` keep exactly one rule, because
a deliberate writer has already read the log it is closing and a second one is a defect worth failing
the read over.

This declaration was prose in the spec and a snippet in `questions/examples/README.md` before it was
code, and the snippet was wrong about `noted` within a day of being written. A claim nobody executes
is a claim nobody checks.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from yosefactory.protocol.eventlog import ANY, Declaration, FoldedLog, Rule
from yosefactory.protocol.eventlog import load as _load

STATES = frozenset({"awaiting", "answered", "timed_out", "cancelled"})

TERMINAL = frozenset({"answered", "timed_out", "cancelled"})

KINDS = (
    "decision",
    "ambiguity",
    "out-of-depth",
    "gate-failed",
    "cost-approval",
    "skip-the-skill",
    "elicitation",
    "goal-falsified",
)

# Blocking-by-design is schedulable in advance; blocking-by-failure arises from something going
# wrong. Derived from `kind` and never written, so the two cannot disagree.
BLOCKING_BY_DESIGN = frozenset({"elicitation"})

_KIND = "|".join(KINDS)
_ON_TIMEOUT = r"escalate|default:.+|abandon:.+"

_AWAITING = frozenset({"awaiting"})

QUESTION = Declaration(
    initial="asked",
    states=STATES,
    terminal=TERMINAL,
    rules={
        "asked": Rule(
            frozenset(),
            "awaiting",
            required=(
                ("item",),
                ("kind",),
                ("to",),
                ("text",),
                ("answer_type",),
                ("return_to",),
                ("deadline",),
                ("on_timeout",),
            ),
            patterns={("kind",): _KIND, ("on_timeout",): _ON_TIMEOUT},
        ),
        "nudged": Rule(_AWAITING, None, required=(("reason",),)),
        # Legal from any state, closed included, so a finished question can still be annotated.
        "noted": Rule(ANY, None, required=(("body",),)),
        "answered": Rule(_AWAITING, "answered", required=(("verdict",), ("answer",))),
        "timed_out": (
            Rule(_AWAITING, "timed_out", required=(("policy",), ("answer",))),
            Rule(TERMINAL, None),
        ),
        "cancelled": Rule(_AWAITING, "cancelled", required=(("reason",),)),
    },
)


def load(path: str | Path) -> FoldedLog:
    return _load(path, QUESTION)


def asked(question: FoldedLog) -> Mapping[str, Any]:
    """The `asked` record, which the fold guarantees is first and present exactly once."""
    return question.records[0]


def blocking_by_design(question: FoldedLog) -> bool:
    return str(asked(question).get("kind", "")) in BLOCKING_BY_DESIGN


def deadline(question: FoldedLog) -> str | None:
    """The question owns its own closure. An item suspended on it reads this rather than a copy."""
    return asked(question).get("deadline")


def on_timeout(question: FoldedLog) -> str | None:
    return asked(question).get("on_timeout")


def outcome(question: FoldedLog) -> Mapping[str, Any] | None:
    """The record that closed the question, or None while it is still awaiting.

    The state's own event, not the last line: a `timed_out` absorbed after an answer is retained in
    the log and is deliberately not the outcome.
    """
    if question.state not in TERMINAL:
        return None
    for record in reversed(question.records):
        if record["event"] == question.state:
            return record
    return None


def absorbed(question: FoldedLog) -> tuple[Mapping[str, Any], ...]:
    """Records a rule accepted without letting them change the state — a sweeper that lost the race.

    Retained rather than tolerated: a late close is evidence about the loop's timing, and a reader
    that cannot see it cannot tell a healthy race from a sweeper that is simply wrong.
    """
    if question.state not in TERMINAL:
        return ()
    closed = outcome(question)
    return tuple(
        record for record in question.records if record["event"] in TERMINAL and record is not closed
    )
