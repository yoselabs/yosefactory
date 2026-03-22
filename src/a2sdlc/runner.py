"""Runner — Claude Agent SDK wrapper with streaming progress."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

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


# ── Context window sizes ───────────────────────────────────────────

_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-sonnet-4-6": 200_000,
    "claude-opus-4-6": 1_000_000,
    "claude-haiku-4-5-20251001": 200_000,
}


def context_window_for_model(model: str) -> int | None:
    """Return context window size for a model, or None if unknown."""
    return _CONTEXT_WINDOWS.get(model)


# ── Formatting helpers ─────────────────────────────────────────────


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
    """Format duration as human-readable string."""
    s = int(seconds)
    if s >= 3600:
        return f"{s // 3600}h {(s % 3600) // 60}m"
    if s >= 60:
        return f"{s // 60}m {s % 60}s"
    return f"{s}s"


def _format_tokens(tokens: int) -> str:
    """Format token count as compact string (e.g. '45k')."""
    k = max(1, round(tokens / 1000)) if tokens > 0 else 0
    return f"{k}k"


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


def format_cost(result: RunResult) -> str:
    """Format cost/usage footer for ticket comments."""
    duration_s = result.duration_ms / 1000
    return (
        f"---\n"
        f"Tokens: {result.input_tokens:,} in / {result.output_tokens:,} out"
        f" | Cost: ${result.total_cost_usd:.2f}"
        f" | Duration: {duration_s:.0f}s"
    )


# ── Progress tracking ───────────────────────────────────────────────


def format_progress(stage: str, tool_log: list[str], start_time: float) -> str:
    """Build a progress comment body from tool log."""
    elapsed = time.time() - start_time
    elapsed_str = f"{elapsed:.0f}s"
    total = len(tool_log)

    lines = [f"⏳ **{stage}** in progress...\n"]
    if total > 10:
        lines.append(f"... and {total - 10} earlier actions\n")
    for tool in tool_log[-10:]:
        lines.append(f"- {tool}")
    lines.append(f"\nTools: {total} | {elapsed_str} elapsed")
    return "\n".join(lines)


# ── Main runner ─────────────────────────────────────────────────────


async def run_stage(
    user_prompt: str,
    system_prompt: str,
    config: StageConfig,
    ticket_key: str,
    stage: str,
    project_root: str,
    is_resume: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> RunResult:
    """Run a pipeline stage using the Claude Agent SDK.

    Streams events in real-time, tracks tool calls for progress,
    and returns a normalized result.
    """
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

    tool_log: list[str] = []
    start_time = time.time()
    last_progress_update = 0.0
    result_msg: ResultMessage | None = None

    timeout_seconds = config.timeout_minutes * 60

    try:

        async def _stream() -> None:
            nonlocal result_msg, last_progress_update
            async for msg in query(prompt=user_prompt, options=options):
                if isinstance(msg, AssistantMessage):
                    _handle_assistant_message(msg, tool_log)

                    # Throttled progress update
                    if on_progress and tool_log:
                        now = time.time()
                        if now - last_progress_update >= 5:
                            on_progress(format_progress(stage, tool_log, start_time))
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
            tool_log=tool_log,
        )
    except Exception as exc:
        logger.exception("SDK error during stage %s", stage)
        return RunResult(
            success=False,
            error=f"sdk_error: {type(exc).__name__}: {exc}",
            session_id=sid,
            tool_log=tool_log,
        )

    if result_msg is None:
        return RunResult(
            success=False,
            error="no_result",
            session_id=sid,
            tool_log=tool_log,
        )

    # Extract usage data — usage may be a dict or an object.
    usage = result_msg.usage or {}
    if isinstance(usage, dict):
        input_tokens = usage.get("input_tokens", 0) or 0
        output_tokens = usage.get("output_tokens", 0) or 0
    else:
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0

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
        tool_log=tool_log,
    )

    logger.info(
        "Stage complete: success=%s cost=$%.4f turns=%d tools=%d output_len=%d",
        run_result.success,
        run_result.total_cost_usd,
        run_result.num_turns,
        len(tool_log),
        len(run_result.output),
    )
    return run_result


def _handle_assistant_message(msg: object, tool_log: list[str]) -> None:
    """Extract tool call names from an AssistantMessage and log them."""
    # SDK puts content directly on AssistantMessage, not on msg.message.
    content = getattr(msg, "content", None)
    if not content:
        return
    for block in content:
        if isinstance(block, ToolUseBlock):
            name = block.name or "unknown"
            tool_log.append(name)
            # GH Actions collapsible group
            print(f"::group::Tool: {name}")  # noqa: T201
            console.log(f"[cyan]Tool:[/cyan] {name}")
            inp = block.input
            if isinstance(inp, dict):
                for k, v in inp.items():
                    console.log(f"  [dim]{k}:[/dim] {str(v)[:100]}")
            print("::endgroup::")  # noqa: T201
        elif isinstance(block, TextBlock):
            if block.text:
                preview = block.text[:200].replace("\n", " ")
                console.log(f"[dim]{preview}[/dim]")
