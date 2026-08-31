"""Renders a turn's trace as a markdown comment body, once, after the run -- never live.

Everything an issue said about a turn was "it started" -- the trace itself lived only in the
runner's private Actions log. `executor.trace.Tracer` (via `executor.stream.StreamReader`) already
turns a `*.stream.jsonl` into human-readable lines; this module is the second half: fold that
trace, plus the item's own event log, into one comment body a caller can post.

Prior art, and the mistake in it: `a2sdlc` posted milestone-section comments too, but updated them
live on every tool call and tripped GitHub's ~1000-content-generating-requests/hour ceiling. This
renders exactly once, from a finished stream, so it also gets the *complete* milestone tree instead
of a partial one -- and it makes no network call at all. Posting the returned string is the
caller's job; the turn itself runs in a container that deliberately holds no issue credential.

Milestones come from the item's own states (`doing`, `gate_rejected`, `done`/`falsified`/`poison`),
never a heuristic -- `protocol.backlog` already folds them, and `claimed.attempt` names the
boundary between one attempt and the next. `current_stream` is the tool trace for the most recent
attempt (in progress or just finished); earlier attempts collapse to their `gate_rejected` report
text, since a past attempt's own stream is not this function's to read unless the caller passes one
in via `prior_streams`.

The status bar's `in / out` figure is the *last turn's* token usage, not a sum across the run.
`terminal.usage` (the `result` event) is a running total over every API call the session made; on a
context that gets re-sent and re-read every turn, summing `cache_read_input_tokens` across turns
counts the same tokens once per turn and grows with turn count alone -- a 66-turn run reads "6033K
in" against "27K out", a ratio that says how long the run was, not how full the context got. The
last turn's own `usage` block (`input_tokens + cache_creation_input_tokens + cache_read_input_tokens`
against that same call's `output_tokens`) is the size of the context as it stood when the run ended,
in the same unit on both sides of the `/` -- what a reader can sanity-check the window against.
Total cost across the run is already reported separately (`total_cost_usd`), which is the right place
for "how much did this consume" to live.
"""

from __future__ import annotations

import bisect
import json
import textwrap
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from yosefactory.executor.stream import StreamReader
from yosefactory.protocol.eventlog import FoldedLog

BODY_LIMIT = 64 * 1024  # GitHub rejects a longer issue-comment body.

_PACKED = "\U0001f4e6"  # a finished, collapsed attempt
_HAMMER = "\U0001f528"  # the open, in-progress attempt
_HOURGLASS = "⏳"  # rejected, waiting on a retry within the same attempt
_DONE = "✅"
_FALSIFIED = "\U0001f504"
_POISON = "☠️"
_FAILED = "❌"
_ROBOT = "\U0001f916"

_STATE_ICON = {
    "done": _DONE,
    "falsified": _FALSIFIED,
    "poison": _POISON,
    "failed": _FAILED,
    "cancelled": _FAILED,
    "abandoned": _FAILED,
    "duplicate": _DONE,
    "blocked": "⏸️",
    "needs_split": "\U0001f9e9",
    "snoozed": "\U0001f4a4",
}

# Generous upper bound for "… 4823 line(s) elided …" -- sized once, not recomputed per digit, since
# the exact count changes it by at most a couple of bytes and this only has to fit under the cap,
# not hit it exactly.
_NOTE_RESERVE = 48


@dataclass
class _Attempt:
    number: int
    report: str | None  # the last `gate_rejected.report` for this attempt, or None
    stream: Path | None  # this attempt's own stream, when one is available to read
    current: bool


@dataclass
class _Section:
    header: str
    icon: str
    open: bool
    lines: list[str] = field(default_factory=list)
    dropped: int = 0


def render(
    current_stream: Path,
    item: FoldedLog | None,
    *,
    prior_streams: Mapping[int, Path] | None = None,
    max_attempts: int = 3,
    body_limit: int = BODY_LIMIT,
    workspace_root: str | None = None,
) -> str:
    """Pure and offline: reads `current_stream` (and `prior_streams`, if given) from disk, folds
    `item`'s own log for milestone boundaries, and returns a markdown body under `body_limit` bytes.

    `item` may be `None` -- an item seeded by hand carries no log yet -- in which case the body is
    the current attempt's trace and status bar alone, with no milestone history. Never raises: a
    missing or unreadable stream renders as an empty trace, not an exception.

    `workspace_root` is the *traced run's own* workspace -- this renderer runs after the run, from
    wherever a comment is being composed, which is never the run's own container. Left `None`, paths
    relativize against the fixed container bind mount only (`executor.trace._CONTAINER_MOUNT`).
    """
    attempts = _attempts(item, current_stream, prior_streams or {})
    sections = [_section_for(a, item, workspace_root) for a in attempts]
    banner = _banner(item, attempts, max_attempts)
    status = _status_bar(current_stream, workspace_root)
    return _fit(banner, sections, status, body_limit)


# -- milestones --------------------------------------------------------------------------------


def _attempts(item: FoldedLog | None, current_stream: Path, prior_streams: Mapping[int, Path]) -> list[_Attempt]:
    if item is None:
        return [_Attempt(number=1, report=None, stream=current_stream, current=True)]
    numbers = sorted({int(record["attempt"]) for record in item.records if record["event"] == "claimed"}) or [1]
    current_number = numbers[-1]
    return [
        _Attempt(
            number=number,
            report=_last_report(item, number),
            stream=current_stream if number == current_number else prior_streams.get(number),
            current=number == current_number,
        )
        for number in numbers
    ]


def _last_report(item: FoldedLog, attempt: int) -> str | None:
    report: str | None = None
    for record in item.records:
        if record["event"] == "gate_rejected" and int(record.get("attempt", -1)) == attempt:
            report = str(record["report"])
    return report


def _banner(item: FoldedLog | None, attempts: list[_Attempt], max_attempts: int) -> str:
    if item is None or not attempts:
        return f"{_HAMMER} in progress"
    state = item.state
    if state == "doing":
        current = attempts[-1]
        icon = _HOURGLASS if current.report else _HAMMER
        label = "gate rejected" if current.report else "in progress"
        return f"{icon} attempt {current.number} of {max_attempts} — {label}"
    icon = _STATE_ICON.get(state, "•")
    return f"{icon} {state.replace('_', ' ')}"


def _section_for(attempt: _Attempt, item: FoldedLog | None, workspace_root: str | None) -> _Section:
    lines = _trace_lines(attempt.stream, workspace_root) if attempt.stream is not None else []
    tool_count = _count_tool_calls(attempt.stream) if attempt.stream is not None else 0
    if not lines and attempt.report:
        lines = [f"  {wrapped}" for wrapped in textwrap.wrap(attempt.report, width=100) or [attempt.report]]

    if attempt.current and item is not None and item.state != "doing":
        icon = _STATE_ICON.get(item.state, _DONE)
        label = item.state.replace("_", " ")
    elif attempt.current:
        icon = _HOURGLASS if attempt.report else _HAMMER
        label = "gate rejected" if attempt.report else "in progress"
    else:
        icon = _PACKED
        label = "gate rejected" if attempt.report else "ended"

    count = f" ({tool_count} tools)" if attempt.stream is not None else ""
    header = f"Attempt {attempt.number} — {label}{count}"
    return _Section(header=header, icon=icon, open=attempt.current, lines=lines)


# -- stream reads --------------------------------------------------------------------------------


def _trace_lines(stream_path: Path, workspace_root: str | None) -> list[str]:
    lines: list[str] = []
    StreamReader(stream_path, sink=lines.append, workspace_root=workspace_root).poll()
    return lines


def _count_tool_calls(stream_path: Path) -> int:
    if not stream_path.exists():
        return 0
    count = 0
    for raw in stream_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "assistant":
            continue
        for block in event.get("message", {}).get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                count += 1
    return count


def _status_bar(stream_path: Path, workspace_root: str | None) -> str:
    reader = StreamReader(stream_path, workspace_root=workspace_root)
    reader.poll()
    terminal: dict[str, Any] = reader.terminal or {}
    usage: dict[str, Any] = reader.last_usage  # the last API call's own usage -- see module docstring
    turns = int(terminal.get("num_turns") or reader.turns)
    cost = float(terminal.get("total_cost_usd") or 0.0)
    duration_ms = terminal.get("duration_ms")
    elapsed = _format_duration(duration_ms) if isinstance(duration_ms, (int, float)) else "?:??"
    model = (reader.init.model if reader.init else "") or "unknown model"
    context_size = (
        int(usage.get("input_tokens") or 0)
        + int(usage.get("cache_creation_input_tokens") or 0)
        + int(usage.get("cache_read_input_tokens") or 0)
    )
    in_tok = _format_tokens(context_size)
    out_tok = _format_tokens(int(usage.get("output_tokens") or 0))
    return (
        f"{_ROBOT} {model} · \U0001f4ca {turns} turns · \U0001f4ac {in_tok} in / {out_tok} out "
        f"· \U0001f4b0 ${cost:.2f} · ⏱ {elapsed}"
    )


def _format_tokens(count: int) -> str:
    return f"{count / 1000:.0f}K" if count >= 1000 else str(count)


def _format_duration(duration_ms: float) -> str:
    minutes, seconds = divmod(max(int(duration_ms / 1000), 0), 60)
    return f"{minutes}m{seconds:02d}s"


# -- the 64KB cap ----------------------------------------------------------------------------


def _build(banner: str, sections: list[_Section], status: str) -> str:
    blocks = [f"### {banner}", *[_render_section(section) for section in sections], f"---\n{status}"]
    return "\n\n".join(blocks)


def _render_section(section: _Section) -> str:
    open_attr = " open" if section.open else ""
    body_lines = list(section.lines)
    if section.dropped:
        body_lines = [f"  … {section.dropped} earlier line(s) elided …", *body_lines]
    body = "\n".join(body_lines) if body_lines else "  (no tool calls)"
    return f"<details{open_attr}><summary>{section.icon} {section.header}</summary>\n\n{body}\n</details>"


def _line_bytes(line: str) -> int:
    return len(line.encode("utf-8")) + 1  # +1 for the newline `_render_section` joins on


def _fit(banner: str, sections: list[_Section], status: str, body_limit: int) -> str:
    full = _build(banner, sections, status)
    if len(full.encode("utf-8")) <= body_limit:
        return full

    # Flatten every section's lines into one oldest-attempt-first, oldest-line-first sequence, so
    # dropping from the front always removes the oldest tool line of the oldest attempt that still
    # has any left -- requirement 4's "drop the oldest tool lines inside a section first."
    starts: list[int] = []
    costs: list[int] = []
    position = 0
    for section in sections:
        starts.append(position)
        for line in section.lines:
            costs.append(_line_bytes(line))
            position += 1

    suffix = [0] * (len(costs) + 1)
    for index in range(len(costs) - 1, -1, -1):
        suffix[index] = suffix[index + 1] + costs[index]

    line_total = suffix[0]
    overhead = len(full.encode("utf-8")) - line_total

    keep_from = len(costs)
    for candidate in range(len(costs) + 1):
        touched = bisect.bisect_right(starts, candidate - 1) if candidate else 0
        if overhead + touched * _NOTE_RESERVE + suffix[candidate] <= body_limit:
            keep_from = candidate
            break

    for index, section in enumerate(sections):
        section_start = starts[index]
        section_end = section_start + len(section.lines)
        cut = max(0, min(keep_from, section_end) - section_start)
        if cut:
            section.lines = section.lines[cut:]
            section.dropped = cut

    return _build(banner, sections, status)
