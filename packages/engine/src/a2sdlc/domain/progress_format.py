"""Progress rendering — pure formatting helpers + context-window lookup.

Inputs come from ``domain.progress`` (events + state) and ``domain.stats``
(accumulated metrics). No I/O.
"""

from __future__ import annotations

import time

from a2sdlc.domain.progress import Milestone, ProgressState
from a2sdlc.domain.stats import StageRunStats


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
    if name in ("Agent", "Task"):
        # Subagent dispatch (Claude Code: Agent, Agent SDK: Task). The
        # caller-supplied `description` is a short 3–5 word purpose;
        # fall back to subagent_type when absent.
        desc = inp.get("description", "")
        if desc:
            return desc[:60]
        return inp.get("subagent_type", "")
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


# Raw.githubusercontent URL for the committed animated spinner. Pinned
# at `main` so the engine tracks whatever asset ships with the current
# release. GitHub's Camo image proxy preserves GIF animation for raw
# URLs on this host, so the spinner actually moves in issue comments.
_SPINNER_URL = (
    "https://raw.githubusercontent.com/yoselabs/a2sdlc/main/assets/spinner.gif"
)


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

    parts = [
        f'<img src="{_SPINNER_URL}" width="14" align="absmiddle" alt="\u23f3"> '
        f"**a2sdlc:{stage}** in progress...\n"
    ]

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
    stats: StageRunStats,
    *,
    model: str,
    branch: str,
    max_turns: int,
    context_window: int | None,
) -> str:
    """Build a status bar from a ``StageRunStats``."""
    return _format_status_bar(
        model=model,
        branch=branch,
        input_tokens=stats.tokens_in,
        output_tokens=stats.tokens_out,
        total_cost_usd=stats.cost_usd,
        duration_seconds=stats.duration_ms / 1000,
        num_turns=stats.num_turns,
        max_turns=max_turns,
        context_window=context_window,
    )


def format_final(
    output: str,
    *,
    stage: str,
    stats: StageRunStats,
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
    stats: StageRunStats,
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
