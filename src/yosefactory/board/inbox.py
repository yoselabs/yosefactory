"""board -> git. The command inbox: read unconsumed events, apply each as an ordinary
backlog/question event, record what happened. Idempotent by the board's own `event_id`.

This is the one module in this capability that reads from the board -- and what it does with the
read is *turn a command into a git append*, never *decide something by inspecting board state*.
Every legality check (`item exists`, `item is blocked`, `is this transition legal`) is answered by
reading git, through the exact same `runtime.turn.append()` primitive `apply_answers()` already
uses for the resolved-question half of this problem (design.md, "Verified before building on it").

Rejection is never a raised exception out of `ingest()` for a single bad command -- one malformed
`/priority` typo must not stop a valid `/answer` two lines below it in the same poll (spec:
"one bad command SHALL NOT stop the rest of the batch"). It is instead a comment posted back on
the thread the command arrived on (design.md D5) and a line in the consumed-log saying so.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from yosefactory.board.adapter import BoardAdapter
from yosefactory.board.event import Event
from yosefactory.protocol import backlog, question
from yosefactory.protocol.eventlog import LogError
from yosefactory.runtime.turn import ITEMS, QUESTIONS, TurnError, new_run_id
from yosefactory.runtime.turn import append as turn_append
from yosefactory.runtime.turn import commit as turn_commit

CONSUMED_LOG = Path("ledger") / "board" / "consumed.jsonl"


@dataclass(frozen=True, slots=True)
class IngestResult:
    event_id: str
    item_id: str | None
    result: str  # "applied" | "rejected"
    detail: str


def _consumed_path(repo: Path) -> Path:
    return repo / CONSUMED_LOG


def _load_consumed(path: Path) -> tuple[set[str], str | None]:
    """The set of already-processed board event_ids, and the offset to resume from.

    The offset is the max board-side `ts` already recorded -- folded from the log itself
    (design.md D4: "never read from a second field that could disagree with it"), never a
    separately stored pointer.
    """
    if not path.exists():
        return set(), None
    ids: set[str] = set()
    since: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        ids.add(str(record["event_id"]))
        board_ts = str(record["board_ts"])
        if since is None or board_ts > since:
            since = board_ts
    return ids, since


def _record_consumed(path: Path, event: Event, result: str, detail: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "event_id": event.event_id,
        "board_ts": event.ts,
        "consumed_at": datetime.now(UTC).isoformat(),
        "type": event.type,
        "actor": event.actor,
        "result": result,
        "detail": detail,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _apply_set_priority(repo: Path, item_id: str, payload: dict[str, Any], *, actor: str) -> tuple[str, Path]:
    item_path = repo / ITEMS / f"{item_id}.jsonl"
    if not item_path.exists():
        raise LookupError(f"item {item_id!r} not found")
    turn_append(item_path, backlog.ITEM, {"event": "priority_set", "priority": payload["priority"]}, actor=actor)
    return f"priority set to {payload['priority']!r}", item_path


def _apply_cancel(repo: Path, item_id: str, payload: dict[str, Any], *, actor: str) -> tuple[str, Path]:
    item_path = repo / ITEMS / f"{item_id}.jsonl"
    if not item_path.exists():
        raise LookupError(f"item {item_id!r} not found")
    turn_append(item_path, backlog.ITEM, {"event": "cancelled", "reason": payload["reason"]}, actor=actor)
    return "cancelled", item_path


def _apply_answer(repo: Path, item_id: str, payload: dict[str, Any], *, actor: str) -> tuple[str, Path]:
    """A free-text `/answer <text>` defaults `verdict` to `accept` -- the question format
    (`protocol/question.py`) requires both fields, and "type something and send it" from a phone
    is not going to also specify a verdict enum. Documented here rather than silently chosen.
    """
    item_path = repo / ITEMS / f"{item_id}.jsonl"
    if not item_path.exists():
        raise LookupError(f"item {item_id!r} not found")
    item = backlog.load(item_path)
    if item.state != "blocked":
        raise LookupError(f"item {item_id!r} is not blocked (state: {item.state!r})")
    awaiting = backlog.awaiting(item)
    if awaiting is None or awaiting.get("kind") not in ("question", "request"):
        raise LookupError(f"item {item_id!r} is blocked but not on a question")
    qid = str(awaiting["ref"])
    question_path = repo / QUESTIONS / f"{qid}.jsonl"
    if not question_path.exists():
        raise LookupError(f"question {qid!r} not found")
    turn_append(question_path, question.QUESTION, {"event": "answered", "verdict": "accept", "answer": payload["answer"]}, actor=actor)
    return f"question {qid} answered; apply_answers() will unblock {item_id} on its next turn", question_path


_APPLIERS = {
    "set_priority": _apply_set_priority,
    "cancel": _apply_cancel,
    "answer": _apply_answer,
}


def ingest(repo: Path, adapter: BoardAdapter, *, actor: str) -> list[IngestResult]:
    """Apply every unconsumed board command. Never raises on a single command's own rejection.

    Every event, applied or rejected, is committed before this returns (board-projection/inbox:
    "a command's effect is committed to git, not left in the working tree") -- one `run_id` shared
    across the whole call, so an `ingest()` pass reads as one platform action in `git log`, the
    same way one `take_turn` call is one action regardless of how many paths it touches.
    """
    path = _consumed_path(repo)
    consumed_ids, since = _load_consumed(path)
    results: list[IngestResult] = []
    run_id = new_run_id()
    for event in adapter.list_events(since):
        if event.event_id in consumed_ids:
            continue  # already processed in a prior run over an overlapping window
        item_id = str(event.payload.get("item_id", "")) or None
        ref = event.payload.get("ref")
        applier = _APPLIERS[event.type]
        try:
            if item_id is None:
                raise LookupError("command carries no item_id")
            detail, touched = applier(repo, item_id, dict(event.payload), actor=actor)
        except (LookupError, LogError, TurnError) as exc:
            detail = str(exc)
            _record_consumed(path, event, "rejected", detail)
            turn_commit(repo, [path], f"board({event.event_id}): {event.type} rejected — {detail}", run_id=run_id)
            results.append(IngestResult(event.event_id, item_id, "rejected", detail))
            if ref is not None:
                adapter.comment(str(ref), f"rejected: {detail}")
            continue
        _record_consumed(path, event, "applied", detail)
        turn_commit(repo, [touched, path], f"board({event.event_id}): {event.type} — {detail}", run_id=run_id)
        results.append(IngestResult(event.event_id, item_id, "applied", detail))
    return results
