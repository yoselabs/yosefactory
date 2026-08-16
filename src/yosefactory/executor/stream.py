"""Reads the agent's own event stream, which is the only thing allowed to say how a run ended.

Three facts about this stream shape everything here, and all three were measured against the binary
rather than taken from documentation:

- **A turn ending is not the run ending.** `system|post_turn_summary` closes a turn; `type: result`
  closes the run. Keying a verdict on the former truncates a run mid-retry and reports success.
- **The terminal event is the verdict gate, and its absence is failure** — on any exit code,
  including zero. In-run failures, missing credentials among them, are printed as ordinary output.
- **`rate_limit_event` is a first-class event.** Quota exhaustion is observed, never inferred from
  the text of an error, because a starved factory that reads as a broken model gets the wrong fix.

The reader is polled while the run is still going, because the turn count has to bound the run
before it ends: the terminal event carries `num_turns`, which arrives too late to enforce anything.
Only whole lines are parsed — a half-written final line is a partial write, not a malformed stream.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from yosefactory.executor.outcome import FailureKind, RunOutcome

_AUTH_STATUSES = frozenset({401, 403})
_RATE_LIMIT_STATUS = 429

# SIGTERM. The supervisor's stop, seen from the child's side of the process boundary.
SIGTERM_EXIT = 143


@dataclass(frozen=True, slots=True)
class InitFacts:
    """What the agent reports about its own configuration at startup.

    Isolation is asserted from these rather than from the arguments we passed. Flags express an
    intent; this is the agent stating what it actually loaded, which is the only one of the two that
    can disagree with reality.
    """

    memory_paths: tuple[str, ...] = ()
    mcp_servers: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    plugins: tuple[str, ...] = ()
    permission_mode: str = ""

    @property
    def leaks(self) -> tuple[str, ...]:
        """Host configuration that reached an agent that was supposed to be isolated."""
        found: list[str] = []
        for name, values in (
            ("memory", self.memory_paths),
            ("mcp", self.mcp_servers),
            ("skills", self.skills),
            ("plugins", self.plugins),
        ):
            if values:
                found.append(f"{name}={len(values)}")
        return tuple(found)


def _names(raw: Any) -> tuple[str, ...]:
    """The stream spells collections several ways; a count that silently reads zero is the hazard."""
    if isinstance(raw, dict):
        return tuple(str(key) for key in raw)
    if isinstance(raw, list):
        return tuple(str(item.get("name", item)) if isinstance(item, dict) else str(item) for item in raw)
    return ()


@dataclass
class StreamReader:
    """Incremental reader over one run's event file. Constructed before the process starts."""

    path: Path
    turns: int = 0
    rate_limited: bool = False
    init: InitFacts | None = None
    terminal: dict[str, Any] | None = None
    _offset: int = field(default=0, repr=False)

    def poll(self) -> None:
        """Consume whole lines written since the last call. Safe to call when the file is absent."""
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(self._offset)
            for line in handle:
                if not line.endswith("\n"):
                    break
                self._offset += len(line.encode("utf-8"))
                stripped = line.strip()
                if stripped:
                    self.consume(stripped)

    def consume(self, line: str) -> None:
        """One event. Public because `--output-format json` emits the same shape as a single line."""
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return
        if not isinstance(event, dict):
            return
        kind = event.get("type")
        if kind == "result":
            self.terminal = event
        elif kind == "rate_limit_event":
            self.rate_limited = True
        elif kind == "system":
            subtype = event.get("subtype")
            if subtype == "post_turn_summary":
                self.turns += 1
            elif subtype == "init":
                self.init = InitFacts(
                    memory_paths=_names(event.get("memory_paths")),
                    mcp_servers=_names(event.get("mcp_servers")),
                    skills=_names(event.get("skills")),
                    plugins=_names(event.get("plugins")),
                    permission_mode=str(event.get("permissionMode", "")),
                )

    def turns_taken(self) -> int:
        self.poll()
        return self.turns

    def classify(self, exit_code: int | None) -> tuple[RunOutcome, FailureKind | None, str]:
        """The verdict. Derived from the terminal event; the exit code only names a missing one."""
        self.poll()
        if self.terminal is None:
            if exit_code == SIGTERM_EXIT:
                return RunOutcome.CANCELLED, None, "terminated before it reported"
            if self.rate_limited:
                return RunOutcome.FAILED, FailureKind.RATE_LIMIT, "quota exhausted, no terminal event"
            return RunOutcome.FAILED, FailureKind.BAD_OUTPUT, "no terminal event"

        event = self.terminal
        status = event.get("api_error_status")
        if isinstance(status, int):
            if status == _RATE_LIMIT_STATUS:
                return RunOutcome.FAILED, FailureKind.RATE_LIMIT, f"api status {status}"
            if status in _AUTH_STATUSES:
                return RunOutcome.FAILED, FailureKind.AUTH, f"api status {status}"

        if event.get("permission_denials"):
            return RunOutcome.NEEDS_APPROVAL, None, "the agent was denied a tool it asked for"

        subtype = str(event.get("subtype", ""))
        if subtype == "error_max_turns":
            return RunOutcome.TURN_LIMIT, None, subtype
        if str(event.get("stop_reason", "")) == "refusal":
            return RunOutcome.REFUSED, None, "refused"
        if not event.get("is_error") and subtype == "success":
            return RunOutcome.SUCCESS, None, ""
        if self.rate_limited:
            return RunOutcome.FAILED, FailureKind.RATE_LIMIT, subtype or "rate limited"
        return RunOutcome.FAILED, FailureKind.TASK_ERROR, subtype or "the agent reported an error"
