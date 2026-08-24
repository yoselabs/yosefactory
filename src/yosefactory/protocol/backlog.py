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

from yosefactory.paths import repo_root
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

# `openspec/specs/backlog-item-format/spec.md` carries this table in human-readable form, for a
# reader (or an unattended agent) without a Python runtime to execute `ITEM.rules` against. This path
# is how `Invocation.vocabulary` points an agent at that mirror — never a second definition of the
# vocabulary, just the pointer.
#
# Resolved by marker walk, not by counting parents: this module's depth under the root is not a fact
# the pointer should depend on. Installed apart from its own `openspec/` tree, `repo_root` raises at
# import rather than handing an agent a path whose `Read` fails with nothing to say about why.
VOCABULARY_SPEC = repo_root() / "openspec" / "specs" / "backlog-item-format" / "spec.md"

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
        # carry-inherited-context-into-the-turn / D030 / S1037: a `done` proposal the gate rejects
        # left no trace on the item at all before this -- the report reached only the ledger's
        # `TurnRecord`, never the log the next attempt actually reads. No existing state-preserving
        # event fits (`frame_amended` and `note` are both excluded by D030 for this purpose), and
        # every other rule reachable from `doing` changes state, which a rejection must not do --
        # the item stays `doing`, retryable within the same attempt.
        "gate_rejected": Rule(
            frozenset({"doing"}), None, required=(("report",), ("attempt",)), types={("report",): str, ("attempt",): int}
        ),
        # unstick-the-backlog / S1021: `claimed.expires_at` was written and read by nothing, so a
        # turn that died after claiming an item parked it in `doing` forever. `reclaimed` is the
        # route back -- distinct fields from `released`'s so a reader can tell "the owner gave it
        # back" from "the owner's lease expired and something else took it back."
        "reclaimed": Rule(
            frozenset({"claimed", "doing"}), "ready", required=(("reason",), ("expired_owner",), ("expired_attempt",))
        ),
        "blocked": Rule(
            frozenset({"claimed", "doing"}),
            "blocked",
            required=tuple(("awaiting", name) for name in _AWAITING_FIELDS),
            patterns={("awaiting", "kind"): _AWAITING_KIND, ("awaiting", "on_timeout"): _ON_TIMEOUT},
        ),
        "unblocked": Rule(
            frozenset({"blocked"}),
            ReturnTo(("awaiting", "return_to")),
            required=(("resolution",),),
            # D032/S246: `resolution` is a dict when an answer resolved the block (`apply_answers`'s
            # own shape, carrying `qid`/`by`/an optional `answer`) and the literal string `"timeout"`
            # when a deadline resolves it instead (`backlog-item-format`'s "The deadline fires"
            # scenario) -- both are legal; a third shape is not.
            types={("resolution",): (str, Mapping)},
        ),
        "snoozed": Rule(frozenset({"ready", "blocked"}), "snoozed", required=(("scheduled_for",),)),
        "woke": Rule(frozenset({"snoozed"}), "ready", required=(("cause",),)),
        "falsified": Rule(frozenset({"doing"}), "falsified", required=(("by",), ("successor",))),
        "failed": Rule(
            frozenset({"claimed", "doing"}),
            "failed",
            required=(("reason",), ("attempt",), ("retryable",)),
            types={("reason",): str, ("attempt",): int, ("retryable",): bool},
        ),
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


def context(item: FoldedLog) -> dict[str, Any]:
    """What attempts before this one produced -- D030's second channel, separate from `frame()`.

    Folds exactly four sources, last-one-wins per source (same pattern as `frame()`): a gate
    rejection, an `unblocked` answer's text, a prior `failed`, and a `released`/`reclaimed` reason.
    `note` is deliberately not folded -- legal in any state with a free-text body, it is what keeps
    this channel unbounded if it is let in, per D030.
    """
    folded: dict[str, Any] = {}
    for record in item.records:
        event = record["event"]
        if event == "gate_rejected":
            folded["gate_rejection"] = {"report": record["report"], "attempt": record["attempt"]}
        elif event == "unblocked":
            # `resolution` is a dict when an answer resolved the block (`apply_answers`'s own
            # shape, carrying `qid`/`by`/an optional `answer`) and the literal string `"timeout"`
            # when a deadline resolved it instead (`sweep_deadlines` / `backlog-item-format`'s "The
            # deadline fires" scenario) -- only the dict shape ever has an answer to carry forward.
            resolution = record.get("resolution")
            answer = resolution.get("answer") if isinstance(resolution, Mapping) else None
            if answer is not None:
                folded["answer"] = answer
        elif event == "failed":
            folded["prior_failure"] = {
                "reason": record["reason"],
                "retryable": record["retryable"],
                "attempt": record["attempt"],
            }
        elif event in ("released", "reclaimed"):
            folded["ended"] = {"event": event, "reason": record["reason"]}
    return folded


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


def claims(item: FoldedLog) -> int:
    """How many times this item has ever been `claimed`, across every `ready` it has passed
    through -- `released` and `reclaimed` both return an item to `ready`, and `lease()` reads
    nothing once that happens, so a claim-time computation keyed off `lease()` alone always sees a
    freshly-`ready` item and always starts over at zero. unstick-the-backlog / S1021: the `attempt`
    field `claimed` writes is meant to survive exactly that reset -- this is what makes it able to.
    """
    return sum(1 for record in item.records if record["event"] == "claimed")


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


def failure(item: FoldedLog) -> Mapping[str, Any] | None:
    """The most recent `failed` record, or None. `retryable`/`attempt` live here -- unstick-the-backlog
    is the first reader of either; the format has required both since it was defined."""
    return _last("failed", item)


def _last(event: str, item: FoldedLog, key: str | None = None) -> Any:
    for record in reversed(item.records):
        if record["event"] == event:
            return record if key is None else record.get(key)
    return None
