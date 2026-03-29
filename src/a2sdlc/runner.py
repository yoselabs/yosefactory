"""Runner — Claude Agent SDK wrapper with streaming progress."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)
from rich.console import Console

from a2sdlc.config import StageConfig, get_session_id

logger = logging.getLogger("a2sdlc.runner")

console = Console(force_terminal=True, force_interactive=False)


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
class ProgressState:
    """Accumulated metrics during stage execution."""

    model: str
    branch: str
    max_turns: int
    context_window: int  # total context window size in tokens
    project_root: str  # for shortening file paths in tool targets
    start_time: float  # time.time() at stage start

    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_usd: float = 0.0
    num_turns: int = 0
    tool_log: list[ToolEntry] = field(default_factory=list)
    milestones: list[Milestone] = field(default_factory=list)


_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-sonnet-4-6": 200_000,
    "claude-opus-4-6": 1_000_000,
    "claude-haiku-4-5-20251001": 200_000,
}


def context_window_for_model(model: str) -> int | None:
    """Return context window size for a model, or None if unknown."""
    return _CONTEXT_WINDOWS.get(model)


def _shorten_path(path: str, project_root: str) -> str:
    """Strip project root prefix from a file path."""
    if not path:
        return ""
    if path.startswith(project_root):
        shortened = path[len(project_root) :]
        return shortened.lstrip("/")
    return path


def _extract_target(name: str, inp: dict, project_root: str) -> str:
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
    return ""


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


def _format_milestones(milestones: list[Milestone]) -> str:
    """Render milestones as persistent pin lines."""
    if not milestones:
        return ""
    lines = []
    for ms in milestones:
        time_str = _format_milestone_time(ms.timestamp)
        lines.append(f"\U0001f4cc {time_str} \u2014 {ms.label}")
    return "\n".join(lines)


@dataclass
class RunResult:
    """Normalized result from a stage execution."""

    success: bool
    output: str = ""
    error: str | None = None
    session_id: str = ""
    total_cost_usd: float = 0.0
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    num_turns: int = 0
    tool_log: list[str] = field(default_factory=list)
    progress: ProgressState | None = None


def format_progress(
    stage: str, progress: ProgressState, *, elapsed: float | None = None
) -> str:
    """Build a progress comment body from ProgressState."""
    if elapsed is None:
        elapsed = time.time() - progress.start_time

    parts = [f"\u23f3 **{stage}** in progress...\n"]

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


def _result_status_bar(
    result: RunResult,
    *,
    model: str,
    branch: str,
    max_turns: int,
    context_window: int | None,
) -> str:
    """Build a status bar from RunResult metadata."""
    return _format_status_bar(
        model=model,
        branch=branch,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        total_cost_usd=result.total_cost_usd,
        duration_seconds=result.duration_ms / 1000,
        num_turns=result.num_turns,
        max_turns=max_turns,
        context_window=context_window,
    )


def format_final(
    result: RunResult,
    *,
    stage: str,
    milestones: list[Milestone],
    model: str,
    branch: str,
    max_turns: int,
    context_window: int | None,
) -> str:
    """Build the final completion comment with status bar and milestones."""
    bar = _result_status_bar(
        result,
        model=model,
        branch=branch,
        max_turns=max_turns,
        context_window=context_window,
    )
    # Strip trailing horizontal rules (--- or ___) left by the agent
    body = (result.output or "").strip()
    while body.endswith("---") or body.endswith("___"):
        body = body[:-3].strip()

    # Build collapsed stats block
    stats_lines = [bar]
    ms_text = _format_milestones(milestones)
    if ms_text:
        stats_lines.append(f"\n{ms_text}")
    stats_body = "\n".join(stats_lines)

    parts = [
        f"### \u2705 {stage}\n",
        body,
        f"\n\n<details>\n<summary>Stats</summary>\n\n{stats_body}\n\n</details>",
    ]
    return "\n".join(parts)


def format_error(
    result: RunResult,
    *,
    stage: str,
    milestones: list[Milestone],
    model: str,
    branch: str,
    max_turns: int,
    context_window: int | None,
) -> str:
    """Build an error comment with status bar and milestones."""
    bar = _result_status_bar(
        result,
        model=model,
        branch=branch,
        max_turns=max_turns,
        context_window=context_window,
    )
    parts = [f"\U0001f6a8 **{stage}** failed: `{result.error}`", "\n---\n", bar]
    ms_text = _format_milestones(milestones)
    if ms_text:
        parts.append(f"\n{ms_text}")
    return "\n".join(parts)


async def run_stage(
    user_prompt: str,
    system_prompt: str,
    config: StageConfig,
    ticket_key: str,
    stage: str,
    project_root: str,
    is_resume: bool = False,
    on_progress: Callable[[str], None] | None = None,
    branch: str = "",
) -> RunResult:
    """Run a pipeline stage via Claude Agent SDK with streaming progress."""
    from claude_agent_sdk import ClaudeAgentOptions, query  # noqa: PLC0415

    sid = get_session_id(ticket_key, stage)
    logger.info(
        "Running stage: ticket=%s stage=%s session=%s resume=%s",
        ticket_key,
        stage,
        sid,
        is_resume,
    )

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        permission_mode="bypassPermissions",
        allowed_tools=config.allowed_tools,
        max_turns=config.max_turns,
        model=config.model,
        cwd=project_root,
    )
    if is_resume:
        options.resume = sid
    else:
        options.session_id = sid

    start_time = time.time()
    last_progress_update = 0.0
    result_msg: ResultMessage | None = None

    progress = ProgressState(
        model=config.model,
        branch=branch,
        max_turns=config.max_turns,
        context_window=context_window_for_model(config.model) or 0,
        project_root=project_root,
        start_time=start_time,
    )

    timeout_seconds = config.timeout_minutes * 60

    try:

        async def _stream() -> None:
            nonlocal result_msg, last_progress_update
            async for msg in query(prompt=user_prompt, options=options):
                if isinstance(msg, AssistantMessage):
                    progress.num_turns += 1
                    _handle_assistant_message(msg, progress)

                    if on_progress and progress.tool_log:  # throttled progress
                        now = time.time()
                        if now - last_progress_update >= 5:
                            on_progress(format_progress(stage, progress))
                            last_progress_update = now

                elif isinstance(msg, ResultMessage):
                    result_msg = msg

        await asyncio.wait_for(_stream(), timeout=timeout_seconds)
    except TimeoutError:
        logger.error(
            "Stage %s timed out after %d minutes", stage, config.timeout_minutes
        )
        return RunResult(
            success=False,
            error=f"timeout ({config.timeout_minutes}min)",
            session_id=sid,
            tool_log=[e.name for e in progress.tool_log],
            progress=progress,
        )
    except Exception as exc:
        logger.exception("SDK error during stage %s", stage)
        return RunResult(
            success=False,
            error=f"sdk_error: {type(exc).__name__}: {exc}",
            session_id=sid,
            tool_log=[e.name for e in progress.tool_log],
            progress=progress,
        )

    if result_msg is None:
        return RunResult(
            success=False,
            error="no_result",
            session_id=sid,
            tool_log=[e.name for e in progress.tool_log],
            progress=progress,
        )

    usage = result_msg.usage or {}
    input_tokens = _get_tokens(usage, "input_tokens")
    output_tokens = _get_tokens(usage, "output_tokens")
    success = getattr(result_msg, "subtype", "") == "success"

    run_result = RunResult(
        success=success,
        output=getattr(result_msg, "result", "") or "",
        error=None if success else getattr(result_msg, "subtype", "unknown"),
        session_id=getattr(result_msg, "session_id", sid) or sid,
        total_cost_usd=getattr(result_msg, "total_cost_usd", 0) or 0,
        duration_ms=getattr(result_msg, "duration_ms", 0) or 0,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        num_turns=getattr(result_msg, "num_turns", 0) or 0,
        tool_log=[e.name for e in progress.tool_log],
        progress=progress,
    )

    logger.info(
        "Stage complete: success=%s cost=$%.4f turns=%d tools=%d output_len=%d",
        run_result.success,
        run_result.total_cost_usd,
        run_result.num_turns,
        len(run_result.tool_log),
        len(run_result.output),
    )
    return run_result


def _get_tokens(usage: Any, field: str) -> int:
    """Safely extract token count from usage (dict or object)."""
    if isinstance(usage, dict):
        return int(usage.get(field, 0) or 0)
    return int(getattr(usage, field, 0) or 0)


def _handle_assistant_message(
    msg: object,
    progress: ProgressState,
    *,
    current_time: float | None = None,
) -> None:
    """Extract tool calls, usage, and milestones from an AssistantMessage."""
    now = current_time if current_time is not None else time.time()
    elapsed = now - progress.start_time

    # Accumulate usage
    usage = getattr(msg, "usage", None)
    if usage:
        progress.input_tokens = _get_tokens(usage, "input_tokens")
        progress.output_tokens = _get_tokens(usage, "output_tokens")
    cost = getattr(msg, "total_cost_usd", None)
    if cost:
        progress.total_cost_usd = cost

    # Process content blocks
    content = getattr(msg, "content", None)
    if not content:
        return
    for block in content:
        if isinstance(block, ToolUseBlock):
            name = block.name or "unknown"
            inp = block.input if isinstance(block.input, dict) else {}
            target = _extract_target(name, inp, progress.project_root)

            progress.tool_log.append(
                ToolEntry(timestamp=elapsed, name=name, target=target)
            )

            # Skill invocation → milestone
            if name == "Skill":
                skill_name = inp.get("skill", "unknown")
                progress.milestones.append(
                    Milestone(timestamp=elapsed, label=f"{skill_name} invoked")
                )

            # GH Actions collapsible group
            print(f"::group::Tool: {name}")  # noqa: T201
            console.log(f"[cyan]Tool:[/cyan] {name}")
            if isinstance(block.input, dict):
                for k, v in block.input.items():
                    console.log(f"  [dim]{k}:[/dim] {str(v)[:100]}")
            print("::endgroup::")  # noqa: T201
        elif isinstance(block, TextBlock):
            if block.text:
                preview = block.text[:200].replace("\n", " ")
                console.log(f"[dim]{preview}[/dim]")
