"""Reads the agent's own event stream, which is the only thing allowed to say how a run ended.

Three facts about this stream shape everything here, and all three were measured against the binary
rather than taken from documentation:

- **A turn ending is not the run ending.** `system|post_turn_summary` closes a turn; `type: result`
  closes the run. Keying a verdict on the former truncates a run mid-retry and reports success.
- **The terminal event is the verdict gate, and its absence is failure** — on any exit code,
  including zero. In-run failures, missing credentials among them, are printed as ordinary output.
- **`rate_limit_event` is a first-class event.** Quota exhaustion is observed, never inferred from
  the text of an error, because a starved factory that reads as a broken model gets the wrong fix.
- **Budget exhaustion is reported, not inferred.** The binary names it in `subtype` and again in
  `terminal_reason`, which is present on every terminal event. It is the same starved-versus-broken
  distinction as the one above, one flag along.

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

# The two names the binary gives one stop. Both are read: `subtype` is the vocabulary everything else
# here classifies from, and `terminal_reason` is the one the binary populates on every terminal event.
_BUDGET_SUBTYPE = "error_max_budget_usd"
_BUDGET_REASON = "budget_exhausted"

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
    slash_commands: tuple[str, ...] = ()
    plugins: tuple[str, ...] = ()
    permission_mode: str = ""
    # What the agent reports it is actually running as, read here rather than from the argument we
    # passed -- the same "verify from what was reported" instrument `leaks` already relies on.
    # Measured (pin-the-executor-and-close-the-push-grant): present on `init` at the pinned version;
    # `effort` is not -- absent from `init`, from every `assistant` message, and from `result`.
    model: str = ""

    @property
    def leaks(self) -> tuple[str, ...]:
        """Host or repository configuration that entered the context of a run that was isolated.

        These four are the surfaces that put instructions in front of the model. A registered plugin
        does not, on its own, which is why it is residue below rather than a breach here.
        """
        found: list[str] = []
        for name, values in (
            ("memory", self.memory_paths),
            ("mcp", self.mcp_servers),
            ("skills", self.skills),
            ("commands", self.slash_commands),
        ):
            if values:
                found.append(f"{name}={len(values)}")
        return tuple(found)

    @property
    def residue(self) -> tuple[str, ...]:
        """Host installations that register under isolation while contributing nothing to context.

        Measured: safe mode still registers one host-installed plugin, and no flag unregisters it —
        only a home the run cannot authenticate from. With commands disabled it supplies zero skills
        and zero commands, so it is recorded rather than treated as a failure. Recorded, because a
        residue nobody writes down is a residue nobody re-measures when the binary moves.
        """
        return (f"plugins={len(self.plugins)}",) if self.plugins else ()

    @property
    def workspace_scope_leaks(self) -> tuple[str, ...]:
        """What `workspace_scoped` can assert absent, from the init event alone.

        `workspace_scoped` admits the repository's own memory, skills and MCP servers by design, so
        the isolated posture's `leaks` (built on the assumption that all four surfaces read empty)
        does not apply. Measured: under `--setting-sources project,local`, host plugin registration
        itself is excluded — unlike under `--safe-mode`, where one host plugin still registers as
        residue. A non-empty `plugins` list under this posture means the run did not get the sources
        it was told to.

        This is the one surface this posture *can* check. Account-level MCP connectors (OAuth-
        registered, distinct from `.mcp.json`/`settings.json` entries) register under every
        `--setting-sources` value measured, including the empty string, and cannot be told apart from
        the workspace's own declared servers without an allowlist this reader does not have — a named
        residue with no control here, recorded in `run-guardrails/agent-isolation`, not something this
        property can detect.
        """
        return (f"plugins={len(self.plugins)}",) if self.plugins else ()


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
                    slash_commands=_names(event.get("slash_commands")),
                    plugins=_names(event.get("plugins")),
                    permission_mode=str(event.get("permissionMode", "")),
                    model=str(event.get("model", "")),
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
        if subtype == _BUDGET_SUBTYPE or str(event.get("terminal_reason", "")) == _BUDGET_REASON:
            # A starved run is not a broken one, and `task_error` is worse here than no answer at
            # all: a null invites the question, a wrong kind answers it and sends someone to debug a
            # factory that only ran out of budget. Measured: the binary reports this stop twice over,
            # in `subtype` and in `terminal_reason`, and both were being dropped.
            return RunOutcome.BUDGET_EXHAUSTED, None, subtype or _BUDGET_REASON
        if str(event.get("stop_reason", "")) == "refusal":
            return RunOutcome.REFUSED, None, "refused"
        if not event.get("is_error") and subtype == "success":
            return RunOutcome.SUCCESS, None, ""
        if self.rate_limited:
            return RunOutcome.FAILED, FailureKind.RATE_LIMIT, subtype or "rate limited"
        return RunOutcome.FAILED, FailureKind.TASK_ERROR, subtype or "the agent reported an error"
