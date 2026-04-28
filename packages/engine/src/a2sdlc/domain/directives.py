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


# Label form: ``gate:merge:human`` / ``gate:merge:auto`` /
# ``gate:spec:human`` / ``gate:spec:auto``. Label names use ``:`` as
# the separator throughout the engine (mirrors ``stage:*`` labels) so
# users can author gate state from the tracker UI without typing
# bracket-form directives in the body. Parser ignores anything
# unrelated; both gate axes accept at most one matching label.
_LABEL_GATE_RE = re.compile(r"^gate:(merge|spec):(human|auto)$")


def parse_label_directives(labels: list[str]) -> TicketDirectives:
    """Build a ``TicketDirectives`` from the live label set on the ticket.

    Maps tracker labels onto the same fields the bracket-form parser
    populates. Only the gate axes are expressible as labels — free-text
    directives (``base``, ``model``) stay in the body. Re-reading the
    label set every dispatch is the engine's responsibility (see ingress);
    this helper is pure.
    """
    directives = TicketDirectives()
    for label in labels:
        match = _LABEL_GATE_RE.match(label)
        if not match:
            continue
        # Regex already restricts value to "human"/"auto" — no ValueError
        # path needed; GateMode() always succeeds here.
        axis, mode = match.group(1), GateMode(match.group(2))
        if axis == "merge":
            directives.gate_merge = mode
        elif axis == "spec":
            directives.gate_spec = mode
    return directives


def merge_directives(
    label_d: TicketDirectives, body_d: TicketDirectives
) -> TicketDirectives:
    """Combine label-derived and body-derived directives.

    Labels are authoritative for the gate axes when present (per the
    gates-via-labels migration plan in TODO). Body directives carry
    the free-text knobs that don't map to labels (``base``, ``model``)
    and act as the fallback gate if no label is set.
    """
    return TicketDirectives(
        base=body_d.base,  # body-only — no label form
        model=body_d.model,  # body-only — no label form
        gate_merge=label_d.gate_merge
        if label_d.gate_merge is not None
        else body_d.gate_merge,
        gate_spec=label_d.gate_spec
        if label_d.gate_spec is not None
        else body_d.gate_spec,
    )
