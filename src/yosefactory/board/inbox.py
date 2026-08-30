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
from yosefactory.runtime.turn import ITEMS, QUESTIONS, TurnError, new_item_id, new_run_id
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

# D031 / design.md ("thin-issue choice"): a GitHub issue supplies at most a title and a body,
# never `goal`/`method`/`assumptions` as such. Building a rigorizer here would contradict D031's
# own boundary -- that step belongs to M440 and applies to every intake door equally -- so a
# missing body is filled with a fixed, honest placeholder rather than invented content.
_NO_METHOD_GIVEN = "(no method given -- the issue body was empty; frame not rigorized)"
_UNRIGORIZED_ASSUMPTIONS = "created from a tracker issue; frame not rigorized (D031, M440 out of scope here)"


def _apply_create(repo: Path, payload: dict[str, Any], *, actor: str) -> tuple[str, str, Path]:
    """No existing item to act on -- allocates one. design.md, "why create is not in _APPLIERS":
    this is the one applier that both manufactures its own `item_id` and needs the caller to reach
    back into the adapter afterward (`project()`, to imprint the marker), so `ingest()` special-
    cases it rather than forcing the shared table into a signature only one row needs.
    """
    item_id = new_item_id()
    item_path = repo / ITEMS / f"{item_id}.jsonl"
    frame = {
        "goal": (str(payload.get("title") or "")).strip() or f"(untitled issue, ref {payload.get('ref')!r})",
        "method": (str(payload.get("body") or "")).strip() or _NO_METHOD_GIVEN,
        "assumptions": _UNRIGORIZED_ASSUMPTIONS,
    }
    turn_append(item_path, backlog.ITEM, {"event": "created", "loop": "board-intake", "frame": frame}, actor=actor)
    return item_id, f"created {item_id} from tracker issue", item_path


def ingest(repo: Path, adapter: BoardAdapter, *, actor: str, allowed_actors: frozenset[str]) -> list[IngestResult]:
    """Apply every unconsumed board command. Never raises on a single command's own rejection.

    Every event, applied or rejected, is committed before this returns (board-projection/inbox:
    "a command's effect is committed to git, not left in the working tree") -- one `run_id` shared
    across the whole call, so an `ingest()` pass reads as one platform action in `git log`, the
    same way one `take_turn` call is one action regardless of how many paths it touches.

    `allowed_actors` is required, with no default: workspaces are public repositories, and without
    an allowlist a stranger's issue or comment becomes a work item an agent spends quota on. This
    is deliberately not the login-based *self*-filter `GitHubIssuesAdapter.list_events` rejects --
    that was about excluding the adapter's own credential, which breaks when the operator and the
    bot share one account. This is the opposite check: an explicit set of *who is allowed in at
    all*, unrelated to which login the adapter itself authenticates as. Matching is
    case-insensitive (GitHub logins are not case-sensitive). A refused event is skipped before it
    is recorded as consumed or acted on in any way -- no item, no comment, no label -- so adding a
    login to the allowlist later makes that person's existing events ingestable with nothing to
    unwind.
    """
    allowed_casefolded = {login.casefold() for login in allowed_actors}
    path = _consumed_path(repo)
    consumed_ids, since = _load_consumed(path)
    results: list[IngestResult] = []
    run_id = new_run_id()
    for event in adapter.list_events(since):
        if event.event_id in consumed_ids:
            continue  # already processed in a prior run over an overlapping window
        if event.actor.casefold() not in allowed_casefolded:
            continue  # not an allowed author -- never recorded as consumed, never commented on
        ref = event.payload.get("ref")

        if event.type == "create":
            # design.md ("why create is not in _APPLIERS"): no existing item_id to dispatch on,
            # and success needs a call back into the adapter the other three never make.
            try:
                item_id, detail, touched = _apply_create(repo, dict(event.payload), actor=actor)
            except (LogError, TurnError) as exc:
                detail = str(exc)
                _record_consumed(path, event, "rejected", detail)
                turn_commit(repo, [path], f"board({event.event_id}): create rejected — {detail}", run_id=run_id)
                results.append(IngestResult(event.event_id, None, "rejected", detail))
                if ref is not None:
                    adapter.comment(str(ref), f"rejected: {detail}")
                continue
            # Structural idempotence (design.md): imprint the new item's marker on the same
            # thread the create event arrived on, before this call returns, so the next
            # list_events() read of this thread's own body already shows it as ingested.
            adapter.project(backlog.load(touched), str(ref))
            _record_consumed(path, event, "applied", detail)
            turn_commit(repo, [touched, path], f"board({event.event_id}): create — {detail}", run_id=run_id)
            results.append(IngestResult(event.event_id, item_id, "applied", detail))
            continue

        item_id = str(event.payload.get("item_id", "")) or None
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
