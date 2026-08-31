"""Renders one human-readable line per stream event, live, as the run happens.

`StreamReader.consume()` reads every event already; before this module the tool-carrying ones
(`assistant`, `user`) were parsed and discarded, so a turn produced no output of its own until its
terminal line. Plain text, no CI markers -- the caller decorates (`::group::` and friends), the
machine reports the same way whether it is run by hand or inside Actions.

Reproducible from a saved `*.stream.jsonl`: every line's elapsed offset is derived from the event's
own `timestamp` field, anchored to the first timestamp seen in the file, never from wall-clock time
read while rendering. Replaying a saved stream through `Tracer` therefore reproduces the same lines,
which is what lets a milestone-comment renderer trust it after the run is long gone.

Tool *content*, not tool names: `read src/x.py`, not `Read`. Everything here truncates -- a tool
input can carry an arbitrary string, and truncation is the only defence this module offers against
printing a secret that happened to be a bash argument or a file's contents.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

_TEXT_LIMIT = 100
_COMMAND_LIMIT = 100
_RESULT_LIMIT = 80
_PATH_LIMIT = 100

_ICONS = {
    "read": "\U0001f4d6 read  ",
    "edit": "\U0001f527 edit  ",
    "multiedit": "\U0001f527 edit  ",
    "write": "\U0001f527 write ",
    "bash": "\U0001f9ea bash  ",
}


def _parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _truncate(text: str, limit: int) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def _diff_size(structured_patch: Any) -> str | None:
    if not isinstance(structured_patch, list):
        return None
    added = removed = 0
    for hunk in structured_patch:
        if not isinstance(hunk, dict):
            continue
        for line in hunk.get("lines", []):
            if not isinstance(line, str):
                continue
            if line.startswith("+"):
                added += 1
            elif line.startswith("-"):
                removed += 1
    return f"(+{added} -{removed})"


def _tool_line(name: str, tool_input: Mapping) -> str:
    lname = name.lower()
    icon = _ICONS.get(lname, "\U0001f529 tool  ")
    if lname == "read":
        return f"{icon}{_truncate(str(tool_input.get('file_path', '')), _PATH_LIMIT)}"
    if lname in ("edit", "multiedit", "write"):
        return f"{icon}{_truncate(str(tool_input.get('file_path', '')), _PATH_LIMIT)}"
    if lname == "bash":
        return f"{icon}{_truncate(str(tool_input.get('command', '')), _COMMAND_LIMIT)}"
    summary = _truncate(json.dumps(tool_input, default=str), _COMMAND_LIMIT) if tool_input else ""
    return f"{icon}{lname} {summary}".rstrip()


@dataclass
class Tracer:
    """Stateful renderer: one instance per run. Call `render()` with every event, in order."""

    _anchor: datetime | None = field(default=None, repr=False)
    _pending: dict[str, tuple[str, dict]] = field(default_factory=dict, repr=False)

    def _offset(self, ts: datetime | None) -> str:
        if ts is None:
            return " ?:??"
        if self._anchor is None:
            self._anchor = ts
        seconds = max(int((ts - self._anchor).total_seconds()), 0)
        minutes, secs = divmod(seconds, 60)
        return f"{minutes:2d}:{secs:02d}"

    @staticmethod
    def _duration_offset(duration_ms: float) -> str:
        minutes, secs = divmod(max(int(duration_ms / 1000), 0), 60)
        return f"{minutes:2d}:{secs:02d}"

    def render(self, event: dict[str, Any]) -> list[str]:
        """The lines this one event produces, in order. Usually zero or one; rarely more."""
        kind = event.get("type")
        ts = _parse_ts(event.get("timestamp"))
        if kind == "assistant":
            return self._render_assistant(event, ts)
        if kind == "user":
            return self._render_tool_result(event, ts)
        if kind == "result":
            return [self._render_result(event, ts)]
        return []

    def _render_assistant(self, event: dict[str, Any], ts: datetime | None) -> list[str]:
        lines: list[str] = []
        offset = self._offset(ts)
        for block in event.get("message", {}).get("content", []) or []:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text = str(block.get("text", "")).strip()
                if text:
                    lines.append(f'{offset}  \U0001f4ac "{_truncate(text, _TEXT_LIMIT)}"')
            elif btype == "tool_use":
                name = str(block.get("name", ""))
                tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
                tool_id = block.get("id")
                if isinstance(tool_id, str):
                    self._pending[tool_id] = (name, tool_input)
                lines.append(f"{offset}  {_tool_line(name, tool_input)}")
        return lines

    def _render_tool_result(self, event: dict[str, Any], ts: datetime | None) -> list[str]:
        tool_use_id = None
        for block in event.get("message", {}).get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                tool_use_id = block.get("tool_use_id")
                break
        if not isinstance(tool_use_id, str) or tool_use_id not in self._pending:
            return []
        name, _tool_input = self._pending.pop(tool_use_id)
        lname = name.lower()
        result = event.get("tool_use_result")
        offset = self._offset(ts)
        if lname == "bash" and isinstance(result, dict):
            out = str(result.get("stdout") or result.get("stderr") or "").strip().splitlines()
            if not out:
                return []
            return [f"{offset}        → {_truncate(out[-1], _RESULT_LIMIT)}"]
        if lname in ("edit", "multiedit", "write") and isinstance(result, dict):
            size = _diff_size(result.get("structuredPatch"))
            if size:
                return [f"{offset}        → {size}"]
        return []

    def _render_result(self, event: dict[str, Any], ts: datetime | None) -> str:
        # Measured: the terminal `result` event carries no `timestamp` of its own (every other
        # event does), but it does carry `duration_ms` -- the run's own wall clock, a better source
        # for this one line than an offset from the first tool call's timestamp would be anyway.
        duration_ms = event.get("duration_ms")
        offset = self._duration_offset(duration_ms) if isinstance(duration_ms, (int, float)) else self._offset(ts)
        icon = "❌" if event.get("is_error") else "✅"
        subtype = str(event.get("subtype", "result"))
        turns = event.get("num_turns", 0)
        cost = float(event.get("total_cost_usd", 0.0) or 0.0)
        return f"{offset}  {icon} result {subtype} · {turns} turns · ${cost:.2f}"
