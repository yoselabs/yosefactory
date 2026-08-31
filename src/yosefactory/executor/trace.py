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

Paths print repo-relative (`src/x.py`, not `/data/workspace/src/x.py`) -- the container bind mount
is the same eleven characters on every line and means nothing to a reader who never had it mounted.
A path outside the repo root (`/app/...`, the image's own tree) is left alone: it is a genuinely
different place, not the same tree with a different prefix, and collapsing the two would make them
indistinguishable.

The `→` line after a bash call states a *shape*, not whatever text happened to come last -- the
last line of a `sed -n` dump is usually a closing paren, not an answer. In order: a non-empty
`stderr` wins outright (the error, not the last line of unrelated stdout); failing that, a test-count
line (`495 passed, 11 deselected in 15.01s`) anywhere in the output wins over whatever follows it;
failing that, a `grep`/`find`-shaped command reports a match count with the first match shown;
failing that, multi-line output reports its line count; a single line is shown as-is.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

_TEXT_LIMIT = 100
_COMMAND_LIMIT = 100
_RESULT_LIMIT = 80
_PATH_LIMIT = 100

# The container's bind mount, fixed regardless of where the *rendering* process happens to sit.
# Relied on only as a fallback when no `workspace_root` travels with the stream -- see `Tracer`.
_CONTAINER_MOUNT = "/data/workspace"

_ICONS = {
    "read": "\U0001f4d6 read  ",
    "edit": "\U0001f527 edit  ",
    "multiedit": "\U0001f527 edit  ",
    "write": "\U0001f527 write ",
    "bash": "\U0001f9ea bash  ",
}

_TEST_COUNT_RE = re.compile(r"\d+ (?:passed|failed|error|skipped|deselected|warning)s?\b")
_SEARCH_CMD_RE = re.compile(r"(?:^|[|;&]|\s)(?:grep|rg|find)\b")


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


def _relativize(path: str, root: str) -> str:
    if path == root:
        return "."
    prefix = root if root.endswith("/") else root + "/"
    return path[len(prefix) :] if path.startswith(prefix) else path


def _diff_size(structured_patch: Any) -> str | None:
    if not isinstance(structured_patch, list) or not structured_patch:
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


def _write_size(content: Any) -> str | None:
    if not isinstance(content, str) or not content:
        return None
    kib = len(content.encode("utf-8")) / 1024
    if kib >= 1:
        return f"{kib:.1f}KB"
    lines = content.count("\n") + (0 if content.endswith("\n") else 1)
    return f"{lines} line{'' if lines == 1 else 's'}"


def _bash_summary(command: str, stdout: str, stderr: str) -> str | None:
    if stderr.strip():
        return _truncate(stderr.strip().splitlines()[0], _RESULT_LIMIT)
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        return None
    for line in reversed(lines):
        if _TEST_COUNT_RE.search(line):
            return _truncate(line.strip(), _RESULT_LIMIT)
    if len(lines) > 1 and _SEARCH_CMD_RE.search(command):
        return _truncate(f"{len(lines)} matches: {lines[0]}", _RESULT_LIMIT)
    if len(lines) > 1:
        return _truncate(f"{len(lines)} lines", _RESULT_LIMIT)
    return _truncate(lines[0], _RESULT_LIMIT)


def _tool_line(name: str, tool_input: Mapping, root: str) -> str:
    lname = name.lower()
    icon = _ICONS.get(lname, "\U0001f529 tool  ")
    if lname == "read":
        return f"{icon}{_truncate(_relativize(str(tool_input.get('file_path', '')), root), _PATH_LIMIT)}"
    if lname in ("edit", "multiedit", "write"):
        return f"{icon}{_truncate(_relativize(str(tool_input.get('file_path', '')), root), _PATH_LIMIT)}"
    if lname == "bash":
        return f"{icon}{_truncate(str(tool_input.get('command', '')), _COMMAND_LIMIT)}"
    summary = _truncate(json.dumps(tool_input, default=str), _COMMAND_LIMIT) if tool_input else ""
    return f"{icon}{lname} {summary}".rstrip()


@dataclass
class Tracer:
    """Stateful renderer: one instance per run. Call `render()` with every event, in order.

    `workspace_root` is the traced run's own workspace, not the rendering process's -- those agree
    only when the tracer happens to run inside the same container the run did, which does not hold
    for `board.trace_comment`, replaying a saved stream from wherever it is invoked. Left unset, only
    the fixed container bind mount (`_CONTAINER_MOUNT`) is recognised, since that much is constant
    across every run regardless of who replays it.
    """

    workspace_root: str = _CONTAINER_MOUNT
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
                lines.append(f"{offset}  {_tool_line(name, tool_input, self.workspace_root)}")
        return lines

    def _render_tool_result(self, event: dict[str, Any], ts: datetime | None) -> list[str]:
        tool_use_id = None
        for block in event.get("message", {}).get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                tool_use_id = block.get("tool_use_id")
                break
        if not isinstance(tool_use_id, str) or tool_use_id not in self._pending:
            return []
        name, tool_input = self._pending.pop(tool_use_id)
        lname = name.lower()
        result = event.get("tool_use_result")
        offset = self._offset(ts)
        if lname == "bash" and isinstance(result, dict):
            command = str(tool_input.get("command", ""))
            stdout = str(result.get("stdout") or "")
            stderr = str(result.get("stderr") or "")
            summary = _bash_summary(command, stdout, stderr)
            if summary is None:
                return []
            return [f"{offset}        → {summary}"]
        if lname == "write" and isinstance(result, dict):
            size = _write_size(result.get("content"))
            return [f"{offset}        → {size}"] if size else []
        if lname in ("edit", "multiedit") and isinstance(result, dict):
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
