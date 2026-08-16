"""The work item's declaration: thirteen states, the event table, and the views folded out of a trail.

This module is data plus small readers. The fold lives in `eventlog` and knows nothing about items.

`terminal` is a predicate over five states, never a state of its own — architecture.md §3. If it were
a state, something would have to write it, and every finished item would then have two
representations of the same fact.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from yosefactory.protocol.eventlog import ANY, ANY_NON_TERMINAL, Declaration, FoldedLog, ReturnTo, Rule
from yosefactory.protocol.eventlog import load as _load

STATES = frozenset(
    {
        "ready",
        "claimed",
        "doing",
        "blocked",
        "falsified",
        "failed",
        "done",
        "cancelled",
        "duplicate",
        "needs_split",
        "snoozed",
        "poison",
        "abandoned",
    }
)

TERMINAL = frozenset({"done", "cancelled", "poison", "duplicate", "abandoned"})

_AWAITING_KIND = "question|request|item"
_ON_TIMEOUT = r"escalate|default:.+|abandon:.+"

# `deadline` and `on_timeout` are not here, and the reason is conditional: a block on a question
# reads them from the question, where they already live, and a second copy is the one that drifts. A
# block of `kind: item` has no question, so it carries them itself — nothing else can, and a block
# with no bound anywhere hangs forever (S172). "Required only when kind is item" is a predicate over
# two fields of one record, which a declaration cannot express, so that half stays writer-enforced.
# The pattern below still checks the value wherever it does appear, since patterns skip absent fields.
_AWAITING_FIELDS = ("kind", "ref", "who", "since", "return_to", "nudge_at")

ITEM = Declaration(
    initial="created",
    states=STATES,
    terminal=TERMINAL,
    rules={
        "created": Rule(frozenset(), "ready", required=(("loop",), ("frame", "goal"), ("frame", "method"), ("frame", "assumptions"))),
        "priority_set": Rule(ANY_NON_TERMINAL, None, required=(("priority",),)),
        "frame_amended": Rule(ANY_NON_TERMINAL, None),
        "claimed": Rule(frozenset({"ready"}), "claimed", required=(("owner",), ("expires_at",), ("attempt",))),
        "started": Rule(frozenset({"claimed"}), "doing"),
        "released": Rule(frozenset({"claimed", "doing"}), "ready", required=(("owner",), ("reason",))),
        "blocked": Rule(
            frozenset({"claimed", "doing"}),
            "blocked",
            required=tuple(("awaiting", name) for name in _AWAITING_FIELDS),
            patterns={("awaiting", "kind"): _AWAITING_KIND, ("awaiting", "on_timeout"): _ON_TIMEOUT},
        ),
        "unblocked": Rule(frozenset({"blocked"}), ReturnTo(("awaiting", "return_to")), required=(("resolution",),)),
        "snoozed": Rule(frozenset({"ready", "blocked"}), "snoozed", required=(("scheduled_for",),)),
        "woke": Rule(frozenset({"snoozed"}), "ready", required=(("cause",),)),
        "falsified": Rule(frozenset({"doing"}), "falsified", required=(("by",), ("successor",))),
        "failed": Rule(frozenset({"claimed", "doing"}), "failed", required=(("reason",), ("attempt",), ("retryable",))),
        "needs_split": Rule(frozenset({"doing"}), "needs_split", required=(("children",),)),
        "done": Rule(frozenset({"doing"}), "done", required=(("effects",), ("verified_by",))),
        "cancelled": Rule(ANY_NON_TERMINAL, "cancelled", required=(("reason",),)),
        "duplicate": Rule(ANY_NON_TERMINAL, "duplicate", required=(("survivor",),)),
        "poisoned": Rule(frozenset({"failed"}), "poison", required=(("attempts",),)),
        "abandoned": Rule(ANY_NON_TERMINAL, "abandoned", required=(("reason",),)),
        "note": Rule(ANY, None, required=(("body",),)),
    },
)


def load(path: str | Path) -> FoldedLog:
    return _load(path, ITEM)


def frame(item: FoldedLog) -> dict[str, Any]:
    """`created`'s frame plus every later amendment. D019: goal, method, assumptions."""
    current: dict[str, Any] = {}
    for record in item.records:
        if record["event"] in ("created", "frame_amended"):
            current.update(record.get("frame", {}))
    return current


def awaiting(item: FoldedLog) -> Mapping[str, Any] | None:
    """The block the item is waiting on, or None. Cleared by the `unblocked` that resolves it."""
    if item.state != "blocked":
        return None
    return _last("blocked", item, key="awaiting")


def lease(item: FoldedLog) -> Mapping[str, Any] | None:
    if item.state not in ("claimed", "doing"):
        return None
    claim = _last("claimed", item)
    if claim is None:
        return None
    return {"owner": claim["owner"], "expires_at": claim["expires_at"], "attempt": claim["attempt"]}


def priority(item: FoldedLog) -> Any:
    return _last("priority_set", item, key="priority")


def successor(item: FoldedLog) -> str | None:
    return _last("falsified", item, key="successor")


def predecessor(item: FoldedLog) -> str | None:
    return item.records[0].get("predecessor")


def survivor(item: FoldedLog) -> str | None:
    return _last("duplicate", item, key="survivor")


def children(item: FoldedLog) -> list[str] | None:
    return _last("needs_split", item, key="children")


def falsification(item: FoldedLog) -> Mapping[str, Any] | None:
    return _last("falsified", item)


def _last(event: str, item: FoldedLog, key: str | None = None) -> Any:
    for record in reversed(item.records):
        if record["event"] == event:
            return record if key is None else record.get(key)
    return None
