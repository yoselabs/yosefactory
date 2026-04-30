"""Progress event taxonomy, Subscriber Protocol, and pub/sub bus (ProgressState).

Pure data + protocols. Formatting/rendering helpers live in
``domain.progress_format``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from a2sdlc.domain.models import StageName
from a2sdlc.domain.stats import StageRunStats


# ── Event taxonomy ────────────────────────────────────────────────


@dataclass
class ToolEntry:
    """Single tool call with context."""

    timestamp: float  # seconds since stage start
    name: str  # tool name (Read, Edit, Bash, etc.)
    target: str  # extracted target (file path, command preview, pattern)


@dataclass
class Milestone:
    """Persistent event that survives comment overwrites."""

    timestamp: float  # seconds since stage start
    label: str  # e.g. "brainstorming invoked"


@dataclass
class StageStart:
    """Stage execution begins. Emitted by dispatch (not the runner)."""

    stage: StageName
    session_id: str
    started_at: float  # time.monotonic() snapshot


@dataclass
class GroupOpen:
    """Open a logical group of related events (e.g. a tool invocation)."""

    title: str


@dataclass
class GroupClose:
    """Close the most-recently-opened group."""


@dataclass
class Metrics:
    """Snapshot of token / cost / turn counters."""

    input_tokens: int
    output_tokens: int
    total_cost_usd: float
    num_turns: int
    elapsed: float  # seconds since stage_start, monotonic clock


@dataclass
class StageEnd:
    """Stage execution ends. Carries authoritative final metrics.

    ``verdict`` is populated for REVIEW stages from the parsed
    ``status`` block (e.g. ``approved`` / ``changes_requested``);
    ``None`` for non-REVIEW stages or when the stage produced no
    parseable status. Renderers fall back to ``success`` for the
    transition label when ``verdict`` is ``None``.
    """

    stage: StageName
    success: bool
    error: str | None
    final_metrics: Metrics
    artifact_path: Path | None = None
    verdict: str | None = None


@dataclass(frozen=True)
class RunEnd:
    """Workflow-level terminal event. Spec §Console output cadence.

    Emitted by pipeline/dispatch.py in a finally block on every exit
    path. Console subscriber renders ``totals:`` (success) or
    ``totals (failed):`` + error message (failure).
    """

    workflow_id: str
    success: bool
    error: str | None
    aggregate_stats: StageRunStats
    total_cycles: dict[StageName, int]


# Tagged union. Subscribers dispatch via isinstance.
ProgressEvent = (
    StageStart
    | ToolEntry
    | GroupOpen
    | GroupClose
    | Metrics
    | Milestone
    | StageEnd
    | RunEnd
)


# ── Subscriber Protocol ───────────────────────────────────────────


class Subscriber(Protocol):
    """Receives ``ProgressEvent`` instances from ``ProgressState``.

    Implementations filter by ``isinstance`` and ignore event types they
    don't care about. ``handle`` is async because the runner is already
    async; sync subscribers just don't ``await`` anything inside.
    """

    async def handle(self, event: "ProgressEvent") -> None: ...


# ── Pub/sub bus ───────────────────────────────────────────────────


@dataclass
class ProgressState:
    """Pub/sub event bus, constructed once per dispatch.

    Per-stage config/counters are refreshed in ``stage_start()``.
    Subscriber list and ``project_root`` survive across stages.
    """

    project_root: str  # for shortening file paths in tool targets

    # Per-stage config (refreshed in stage_start)
    model: str = ""
    branch: str = ""
    max_turns: int = 0
    context_window: int = 0  # total context window size in tokens
    start_time: float = 0.0  # time.monotonic() at most-recent stage_start

    # Per-stage counters (reset in stage_start)
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_usd: float = 0.0
    num_turns: int = 0
    tool_log: list[ToolEntry] = field(default_factory=list)
    milestones: list[Milestone] = field(default_factory=list)
    tasks: dict[str, str] = field(default_factory=dict)  # subject → status

    # Subscriber registry; _failed cleared per stage
    _subscribers: list = field(default_factory=list, init=False, repr=False)
    _failed: set[int] = field(default_factory=set, init=False, repr=False)

    def subscribe(self, sub: Subscriber) -> None:
        """Register a subscriber. Call before any stage_start()."""
        self._subscribers.append(sub)

    async def _emit(self, event: ProgressEvent) -> None:
        # Snapshot so _failed mutation mid-iteration is safe.
        for sub in list(self._subscribers):
            if id(sub) in self._failed:
                continue
            try:
                await sub.handle(event)
            except Exception:  # noqa: BLE001
                logging.getLogger("a2sdlc.progress").exception(
                    "Subscriber %s failed; skipping for remainder of stage",
                    type(sub).__name__,
                )
                self._failed.add(id(sub))

    async def stage_start(
        self,
        stage: StageName,
        session_id: str,
        *,
        model: str,
        max_turns: int,
        context_window: int,
        branch: str,
    ) -> None:
        """Begin a stage: refresh per-stage config and reset counters."""
        self.model = model
        self.max_turns = max_turns
        self.context_window = context_window
        self.branch = branch
        # subscriber list and project_root survive across stages
        self._failed.clear()
        self.tool_log.clear()
        self.milestones.clear()
        self.tasks.clear()
        self.input_tokens = 0
        self.output_tokens = 0
        self.num_turns = 0
        self.total_cost_usd = 0.0
        self.start_time = time.monotonic()
        await self._emit(
            StageStart(stage=stage, session_id=session_id, started_at=self.start_time)
        )

    async def stage_end(
        self,
        stage: StageName,
        success: bool,
        error: str | None,
        final: Metrics,
    ) -> None:
        """End a stage. Emits StageEnd with the authoritative final metrics."""
        await self._emit(
            StageEnd(stage=stage, success=success, error=error, final_metrics=final)
        )

    async def run_end(
        self,
        *,
        workflow_id: str,
        success: bool,
        error: str | None,
        aggregate_stats: StageRunStats,
        total_cycles: dict[StageName, int],
    ) -> None:
        """Emit terminal ``RunEnd`` event. Best-effort: dispatch's
        finally block calls this and swallows any failures.
        """
        await self._emit(
            RunEnd(
                workflow_id=workflow_id,
                success=success,
                error=error,
                aggregate_stats=aggregate_stats,
                total_cycles=total_cycles,
            )
        )

    async def add_tool_call(self, name: str, target: str) -> None:
        elapsed = time.monotonic() - self.start_time
        entry = ToolEntry(timestamp=elapsed, name=name, target=target)
        self.tool_log.append(entry)
        await self._emit(entry)

    async def update_metrics(
        self, tin: int, tout: int, cost: float, turns: int
    ) -> None:
        self.input_tokens = tin
        self.output_tokens = tout
        self.total_cost_usd = cost
        self.num_turns = turns
        elapsed = time.monotonic() - self.start_time
        await self._emit(
            Metrics(
                input_tokens=tin,
                output_tokens=tout,
                total_cost_usd=cost,
                num_turns=turns,
                elapsed=elapsed,
            )
        )

    async def add_milestone(self, label: str) -> None:
        elapsed = time.monotonic() - self.start_time
        m = Milestone(timestamp=elapsed, label=label)
        self.milestones.append(m)
        await self._emit(m)

    async def open_group(self, title: str) -> None:
        await self._emit(GroupOpen(title=title))

    async def close_group(self) -> None:
        await self._emit(GroupClose())

    def snapshot_metrics(self) -> Metrics:
        """Build a Metrics record from current counters. No emit."""
        elapsed = time.monotonic() - self.start_time if self.start_time else 0.0
        return Metrics(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            total_cost_usd=self.total_cost_usd,
            num_turns=self.num_turns,
            elapsed=elapsed,
        )
