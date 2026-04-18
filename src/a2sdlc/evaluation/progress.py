"""Progress tracking — dataclasses, formatting, and rendering for stage comments."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from a2sdlc.domain.models import StageName

if TYPE_CHECKING:
    from a2sdlc.adapters.protocols import Subscriber


# ── Data models ────────────────────────────────────────────────────


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


# ── Event taxonomy ─────────────────────────────────────────────────
# ToolEntry (above) and Milestone (above) double as event types.


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
    """Stage execution ends. Carries authoritative final metrics."""

    stage: StageName
    success: bool
    error: str | None
    final_metrics: Metrics


# Tagged union. Subscribers dispatch via isinstance.
ProgressEvent = (
    StageStart | ToolEntry | GroupOpen | GroupClose | Metrics | Milestone | StageEnd
)


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

    def subscribe(self, sub: "Subscriber") -> None:
        """Register a subscriber. Call before any stage_start()."""
        self._subscribers.append(sub)

    async def _emit(self, event: "ProgressEvent") -> None:
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
        final: "Metrics",
    ) -> None:
        """End a stage. Emits StageEnd with the authoritative final metrics."""
        await self._emit(
            StageEnd(stage=stage, success=success, error=error, final_metrics=final)
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

    def snapshot_metrics(self) -> "Metrics":
        """Build a Metrics record from current counters. No emit."""
        elapsed = time.monotonic() - self.start_time if self.start_time else 0.0
        return Metrics(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            total_cost_usd=self.total_cost_usd,
            num_turns=self.num_turns,
            elapsed=elapsed,
        )


# ── Context window sizes ──────────────────────────────────────────

_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-sonnet-4-6": 200_000,
    "claude-opus-4-6": 1_000_000,
    "claude-haiku-4-5-20251001": 200_000,
}


def context_window_for_model(model: str) -> int | None:
    """Return context window size for a model, or None if unknown."""
    return _CONTEXT_WINDOWS.get(model)


# ── Extraction helpers ────────────────────────────────────────────


def _shorten_path(path: str, project_root: str) -> str:
    """Strip project root prefix from a file path."""
    if not path:
        return ""
    if path.startswith(project_root):
        shortened = path[len(project_root) :]
        return shortened.lstrip("/")
    return path


def extract_target(name: str, inp: dict, project_root: str) -> str:
    """Extract a human-readable target from tool input."""
    if name in ("Read", "Edit", "Write"):
        path = inp.get("file_path", "")
        return _shorten_path(path, project_root) if path else ""
    if name in ("Glob", "Grep"):
        return inp.get("pattern", "") or inp.get("path", "") or ""
    if name == "Bash":
        cmd = inp.get("command", "")
        return f"`{cmd[:60]}`" if cmd else ""
    if name == "Skill":
        return inp.get("skill", "")
    if name == "TodoWrite":
        todos = inp.get("todos", [])
        if isinstance(todos, list) and todos:
            count = len(todos)
            first = todos[0].get("content", "") if isinstance(todos[0], dict) else ""
            if count == 1:
                return first[:50]
            return f"{count} tasks"
        return ""
    return ""


# ── Formatting helpers ────────────────────────────────────────────


def _format_duration(seconds: float) -> str:
    s = int(seconds)
    if s >= 3600:
        return f"{s // 3600}h {(s % 3600) // 60}m"
    return f"{s // 60}m {s % 60}s" if s >= 60 else f"{s}s"


def _format_tokens(tokens: int) -> str:
    k = max(1, round(tokens / 1000)) if tokens > 0 else 0
    return f"{k}k"


def _format_milestone_time(seconds: float) -> str:
    m, s = int(seconds) // 60, int(seconds) % 60
    return f"{m}:{s:02d}"


def _format_status_bar(
    *,
    model: str,
    branch: str,
    input_tokens: int,
    output_tokens: int,
    total_cost_usd: float,
    duration_seconds: float,
    num_turns: int,
    max_turns: int,
    context_window: int | None,
) -> str:
    """Render a single-row markdown table status bar."""
    if input_tokens == 0 and output_tokens == 0 and total_cost_usd == 0.0:
        tokens_str = "\u2014"
        cost_str = "\u2014"
        context_str = "\u2014"
    else:
        tokens_str = (
            f"{_format_tokens(input_tokens)} in / {_format_tokens(output_tokens)} out"
        )
        cost_str = f"${total_cost_usd:.2f}"
        if context_window:
            pct = int(input_tokens / context_window * 100)
            ctx_k = context_window // 1000
            context_str = f"{_format_tokens(input_tokens)}/{ctx_k}k ({pct}%)"
        else:
            context_str = _format_tokens(input_tokens)

    duration_str = _format_duration(duration_seconds)
    turns_str = f"{num_turns}/{max_turns}"

    header = "| Model | Branch | Context | Cost | Tokens | Duration | Turns |"
    sep = "|-------|--------|---------|------|--------|----------|-------|"
    row = f"| {model} | {branch} | {context_str} | {cost_str} | {tokens_str} | {duration_str} | {turns_str} |"
    return f"{header}\n{sep}\n{row}"


_TASK_ICONS: dict[str, str] = {
    "completed": "\u2705",
    "in_progress": "\U0001f504",
    "pending": "\u2b1c",
}


def _format_tasks(tasks: dict[str, str]) -> str:
    """Render task list with status icons."""
    if not tasks:
        return ""
    lines = []
    for subject, status in tasks.items():
        icon = _TASK_ICONS.get(status, "\u2b1c")
        lines.append(f"{icon} {subject}")
    return "\n".join(lines)


def _format_milestones(milestones: list[Milestone]) -> str:
    """Render milestones as persistent pin lines."""
    if not milestones:
        return ""
    lines = []
    for ms in milestones:
        time_str = _format_milestone_time(ms.timestamp)
        lines.append(f"\U0001f4cc {time_str} \u2014 {ms.label}")
    return "\n".join(lines)


# ── Public rendering functions ────────────────────────────────────


def format_progress(
    stage: str, progress: ProgressState, *, elapsed: float | None = None
) -> str:
    """Build a progress comment body from ProgressState."""
    if elapsed is None:
        elapsed = time.monotonic() - progress.start_time

    parts = [f"\u23f3 **a2sdlc:{stage}** in progress...\n"]

    parts.append(
        _format_status_bar(
            model=progress.model,
            branch=progress.branch,
            input_tokens=progress.input_tokens,
            output_tokens=progress.output_tokens,
            total_cost_usd=progress.total_cost_usd,
            duration_seconds=elapsed,
            num_turns=progress.num_turns,
            max_turns=progress.max_turns,
            context_window=progress.context_window
            if progress.context_window > 0
            else None,
        )
    )

    ms_text = _format_milestones(progress.milestones)
    if ms_text:
        parts.append(f"\n{ms_text}")

    tasks_text = _format_tasks(progress.tasks)
    if tasks_text:
        parts.append(f"\n{tasks_text}")

    if progress.tool_log:
        parts.append("")
        header = "| Time | Tool | Target |"
        sep = "|------|------|--------|"
        parts.append(header)
        parts.append(sep)
        total = len(progress.tool_log)
        if total > 10:
            parts.append(f"| ... | | *({total - 10} earlier)* |")
        for entry in progress.tool_log[-10:]:
            t = _format_milestone_time(entry.timestamp)
            parts.append(f"| {t} | {entry.name} | {entry.target} |")

    return "\n".join(parts)


def _stats_bar(
    stats: object,
    *,
    model: str,
    branch: str,
    max_turns: int,
    context_window: int | None,
) -> str:
    """Build a status bar from a StageRunStats-like object."""
    return _format_status_bar(
        model=model,
        branch=branch,
        input_tokens=getattr(stats, "tokens_in", 0) or 0,
        output_tokens=getattr(stats, "tokens_out", 0) or 0,
        total_cost_usd=getattr(stats, "cost_usd", 0.0) or 0.0,
        duration_seconds=(getattr(stats, "duration_ms", 0) or 0) / 1000,
        num_turns=getattr(stats, "num_turns", 0) or 0,
        max_turns=max_turns,
        context_window=context_window,
    )


def format_final(
    output: str,
    *,
    stage: str,
    stats: object,
    milestones: list[Milestone],
    model: str,
    branch: str,
    max_turns: int,
    context_window: int | None,
    tasks: dict[str, str] | None = None,
) -> str:
    """Build the final completion comment with collapsed stats."""
    bar = _stats_bar(
        stats,
        model=model,
        branch=branch,
        max_turns=max_turns,
        context_window=context_window,
    )
    body = output.strip()
    while body.endswith("---") or body.endswith("___"):
        body = body[:-3].strip()
    stats_lines = [bar]
    ms_text = _format_milestones(milestones)
    if ms_text:
        stats_lines.append(f"\n{ms_text}")
    if tasks:
        tasks_text = _format_tasks(tasks)
        if tasks_text:
            stats_lines.append(f"\n{tasks_text}")
    stats_body = "\n".join(stats_lines)
    parts = [
        f"### \u2705 a2sdlc:{stage}\n",
        body,
        f"\n\n<details>\n<summary>Stats</summary>\n\n{stats_body}\n\n</details>",
    ]
    return "\n".join(parts)


def format_error(
    error: str,
    *,
    stage: str,
    stats: object,
    milestones: list[Milestone],
    model: str,
    branch: str,
    max_turns: int,
    context_window: int | None,
) -> str:
    """Build an error comment with status bar and milestones."""
    bar = _stats_bar(
        stats,
        model=model,
        branch=branch,
        max_turns=max_turns,
        context_window=context_window,
    )
    parts = [f"\U0001f6a8 **a2sdlc:{stage}** failed: `{error}`", "\n---\n", bar]
    ms_text = _format_milestones(milestones)
    if ms_text:
        parts.append(f"\n{ms_text}")
    return "\n".join(parts)
