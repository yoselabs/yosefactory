"""Ticket directive parsing — extract ``[a2sdlc key=value]`` blocks from body."""

from __future__ import annotations

import re

from pydantic import BaseModel

from a2sdlc.domain.models import GateMode

# Matches a full [a2sdlc ...] line including its trailing newline (if any).
_DIRECTIVE_LINE_RE = re.compile(r"^\[a2sdlc([^\]]*)\]\s*\n?", re.MULTILINE)

# Matches a single key=value token (colons in keys are allowed).
_KV_RE = re.compile(r"([\w:]+)=([\S]+)")


class TicketDirectives(BaseModel):
    """Parsed directives extracted from a ticket body."""

    base: str | None = None
    gate_merge: GateMode | None = None
    gate_spec: GateMode | None = None
    model: str | None = None


def _apply_kv(directives: TicketDirectives, key: str, value: str) -> None:
    """Apply a single key=value pair to *directives* in-place, silently ignoring unknowns."""
    if key == "base":
        directives.base = value
    elif key == "gate:merge":
        try:
            directives.gate_merge = GateMode(value)
        except ValueError:
            pass
    elif key == "gate:spec":
        try:
            directives.gate_spec = GateMode(value)
        except ValueError:
            pass
    elif key == "model":
        directives.model = value
    # Unknown keys are silently ignored.


def parse_directives(body: str) -> tuple[TicketDirectives, str]:
    """Extract all ``[a2sdlc ...]`` lines from *body*.

    Returns a tuple of ``(TicketDirectives, cleaned_body)`` where the directive
    lines have been removed and the remaining body is whitespace-trimmed.
    """
    directives = TicketDirectives()

    def _handle_match(m: re.Match[str]) -> str:  # type: ignore[type-arg]
        content = m.group(1).strip()
        if not content:
            # Empty brackets — silently ignore but still strip the line.
            return ""
        for kv_match in _KV_RE.finditer(content):
            _apply_kv(directives, kv_match.group(1), kv_match.group(2))
        return ""

    cleaned = _DIRECTIVE_LINE_RE.sub(_handle_match, body)
    cleaned = cleaned.strip()

    return directives, cleaned
