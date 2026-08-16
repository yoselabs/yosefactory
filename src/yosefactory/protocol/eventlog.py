"""Fold an append-only event log into current state.

The fold is generic on purpose. D020 makes a cross-repo request a question, and a question and a
work item the same object in different states, so there is one fold over one storage shape and each
kind supplies a `Declaration` — states, terminal set, transition table. Nothing here knows what a
backlog item is.

Two properties this module must keep, because the rest of the design leans on them:

* **Order-insensitive.** A git merge interleaves appended lines and `merge=union` can duplicate
  them, so replay order comes from `ts` and `event_id`, never from position in the file.
* **Loud.** An unknown event, an illegal transition or a malformed line fails the read. A reader
  that skips what it does not understand reports a state that never existed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

REQUIRED_FIELDS: Final[tuple[str, ...]] = ("event_id", "ts", "actor", "event")

ANY: Final = "<any>"
ANY_NON_TERMINAL: Final = "<any-non-terminal>"

Record = Mapping[str, Any]
Path_ = tuple[str, ...]


class LogError(Exception):
    """A log that cannot be read. Carries enough to find the line by hand."""

    def __init__(self, message: str, *, source: str, line: int | None = None) -> None:
        where = f"{source}:{line}" if line is not None else source
        super().__init__(f"{where}: {message}")
        self.source = source
        self.line = line


@dataclass(frozen=True)
class ReturnTo:
    """A transition target read from the event that put the item in its current state.

    `blocked` stores where to come back to; `unblocked` goes there rather than recomputing it.
    """

    path: Path_


@dataclass(frozen=True)
class Rule:
    from_states: frozenset[str] | str
    to: str | ReturnTo | None
    required: tuple[Path_, ...] = ()
    patterns: Mapping[Path_, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Declaration:
    initial: str
    states: frozenset[str]
    terminal: frozenset[str]
    rules: Mapping[str, Rule]


@dataclass(frozen=True)
class FoldedLog:
    id: str
    state: str
    records: tuple[Record, ...]
    declaration: Declaration

    @property
    def terminal(self) -> bool:
        return self.state in self.declaration.terminal


def load(path: str | Path, declaration: Declaration, *, log_id: str | None = None) -> FoldedLog:
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as exc:
        raise LogError(str(exc), source=str(file)) from exc
    return loads(text, declaration, source=str(file), log_id=log_id or file.stem)


def loads(text: str, declaration: Declaration, *, source: str, log_id: str) -> FoldedLog:
    records = _dedup(_parse(text, source), source)
    state = _fold(records, declaration, source)
    return FoldedLog(id=log_id, state=state, records=records, declaration=declaration)


def _parse(text: str, source: str) -> list[Record]:
    records: list[Record] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LogError(f"not valid JSON ({exc.msg})", source=source, line=number) from exc
        if not isinstance(record, dict):
            raise LogError(f"expected a JSON object, found {type(record).__name__}", source=source, line=number)
        missing = [name for name in REQUIRED_FIELDS if name not in record]
        if missing:
            raise LogError(f"missing required field(s): {', '.join(missing)}", source=source, line=number)
        record["_line"] = number
        records.append(record)
    if not records:
        raise LogError("empty log", source=source)
    return records


def _dedup(records: Sequence[Record], source: str) -> tuple[Record, ...]:
    ordered = sorted(records, key=lambda record: (str(record["ts"]), str(record["event_id"])))
    seen: dict[str, Record] = {}
    kept: list[Record] = []
    for record in ordered:
        event_id = str(record["event_id"])
        first = seen.get(event_id)
        if first is None:
            seen[event_id] = record
            kept.append(record)
            continue
        if _payload(first) != _payload(record):
            raise LogError(
                f"event_id {event_id!r} appears twice with different content (also line {first['_line']})",
                source=source,
                line=record["_line"],
            )
    return tuple(kept)


def _payload(record: Record) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key != "_line"}


def _fold(records: Sequence[Record], declaration: Declaration, source: str) -> str:
    state = ""
    arrivals: list[tuple[str, Record]] = []
    for position, record in enumerate(records):
        name = str(record["event"])
        rule = declaration.rules.get(name)
        line = record["_line"]
        if rule is None:
            raise LogError(f"unknown event {name!r}", source=source, line=line)
        if position == 0 and name != declaration.initial:
            raise LogError(f"log opens with {name!r}; expected {declaration.initial!r}", source=source, line=line)
        if position > 0 and name == declaration.initial:
            raise LogError(f"{name!r} may only be the first event", source=source, line=line)
        if position > 0:
            _check_from(rule, state, name, declaration, source, line)
        _check_payload(rule, record, name, source, line)
        target = _target(rule, state, arrivals, name, source, line)
        if target is not None:
            if target not in declaration.states:
                raise LogError(f"{name!r} transitions to undeclared state {target!r}", source=source, line=line)
            state = target
            arrivals.append((state, record))
    return state


def _check_from(rule: Rule, state: str, name: str, declaration: Declaration, source: str, line: int) -> None:
    if rule.from_states == ANY:
        return
    if state in declaration.terminal:
        raise LogError(f"{name!r} is illegal from terminal state {state!r}", source=source, line=line)
    if rule.from_states == ANY_NON_TERMINAL:
        return
    if state not in rule.from_states:
        legal = ", ".join(sorted(rule.from_states)) if isinstance(rule.from_states, frozenset) else str(rule.from_states)
        raise LogError(f"{name!r} is illegal from state {state!r}; legal from: {legal}", source=source, line=line)


def _check_payload(rule: Rule, record: Record, name: str, source: str, line: int) -> None:
    for path in rule.required:
        found, _ = _dig(record, path)
        if not found:
            raise LogError(f"{name!r} is missing required field {'.'.join(path)!r}", source=source, line=line)
    for path, pattern in rule.patterns.items():
        found, value = _dig(record, path)
        if not found:
            continue
        if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
            raise LogError(f"{'.'.join(path)} is {value!r}, which does not match {pattern!r}", source=source, line=line)


def _target(rule: Rule, state: str, arrivals: Sequence[tuple[str, Record]], name: str, source: str, line: int) -> str | None:
    if rule.to is None or isinstance(rule.to, str):
        return rule.to
    for arrived_at, record in reversed(arrivals):
        if arrived_at != state:
            continue
        found, value = _dig(record, rule.to.path)
        if not found or not isinstance(value, str):
            raise LogError(
                f"{name!r} returns to {'.'.join(rule.to.path)}, which the event that entered {state!r} did not store",
                source=source,
                line=line,
            )
        return value
    raise LogError(f"{name!r} returns to a stored state, but nothing recorded entering {state!r}", source=source, line=line)


def _dig(record: Record, path: Path_) -> tuple[bool, Any]:
    value: Any = record
    for key in path:
        if not isinstance(value, Mapping) or key not in value:
            return False, None
        value = value[key]
    return True, value
