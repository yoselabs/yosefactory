"""Runner — Claude Agent SDK wrapper with streaming progress."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from rich.console import Console

from a2sdlc.config import StageConfig, get_session_id

logger = logging.getLogger("a2sdlc.runner")

console = Console(force_terminal=True, force_interactive=False)


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
    from claude_agent_sdk import (  # noqa: PLC0415
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        query,
    )

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

    try:
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
    except Exception:
        logger.exception("SDK error during stage %s", stage)
        return RunResult(
            success=False,
            error="sdk_error",
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
    message = getattr(msg, "message", None)
    if message is None:
        return
    content = getattr(message, "content", None)
    if not content:
        return
    for block in content:
        block_type = getattr(block, "type", None)
        if block_type == "tool_use":
            name = getattr(block, "name", "unknown")
            tool_log.append(name)
            console.log(f"[cyan]Tool:[/cyan] {name}")
        elif block_type == "text":
            text = getattr(block, "text", "")
            if text:
                preview = text[:120].replace("\n", " ")
                console.log(f"[dim]{preview}[/dim]")
