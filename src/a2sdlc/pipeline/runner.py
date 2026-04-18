"""Runner — Claude Agent SDK wrapper with streaming progress."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)
from rich.console import Console

from a2sdlc.adapters.protocols import ProgressAdapter
from a2sdlc.config import StageConfig, get_session_id
from a2sdlc.domain.models import StageName
from a2sdlc.domain.run_result import RunResult
from a2sdlc.evaluation.progress import (
    Milestone,
    ProgressState,
    ToolEntry,
    extract_target,
    context_window_for_model,
    format_progress,
)

logger = logging.getLogger("a2sdlc.pipeline.runner")

console = Console(force_terminal=True, force_interactive=False)


# Maps a2sdlc's ``effort`` config value to the SDK's ``ClaudeAgentOptions.effort``
# literal. a2sdlc exposes ``xhigh`` as the top tier; the SDK calls it ``max``.
_EFFORT_SDK_MAP: dict[str, str] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "max",
}


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
    branch: str = "",
    progress_adapter: ProgressAdapter | None = None,
    effort: str | None = None,
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

    options_kwargs: dict[str, Any] = {
        "system_prompt": system_prompt,
        "permission_mode": "bypassPermissions",
        "allowed_tools": config.allowed_tools,
        "max_turns": config.max_turns,
        "model": config.model,
        "cwd": project_root,
        # Exclude user-level Claude Code settings (~/.claude/CLAUDE.md,
        # auto-memory) so the agent runs with only project + local context.
        # a2sdlc is a self-contained pipeline; personal instructions from the
        # invoking user's global config would bleed unrelated context in.
        "setting_sources": ["project", "local"],
    }
    if effort is not None:
        sdk_effort = _EFFORT_SDK_MAP.get(effort)
        if sdk_effort is None:
            raise ValueError(
                f"Invalid effort {effort!r}. Expected one of {sorted(_EFFORT_SDK_MAP)}."
            )
        options_kwargs["effort"] = sdk_effort

    options = ClaudeAgentOptions(**options_kwargs)
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
                    _handle_assistant_message(
                        msg, progress, progress_adapter=progress_adapter
                    )

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
    progress_adapter: ProgressAdapter | None = None,
) -> None:
    """Extract tool calls, usage, and milestones from an AssistantMessage."""
    now = current_time if current_time is not None else time.monotonic()
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
            target = extract_target(name, inp, progress.project_root)

            progress.tool_log.append(
                ToolEntry(timestamp=elapsed, name=name, target=target)
            )

            # Skill invocation → milestone
            if name == "Skill":
                skill_name = inp.get("skill", "unknown")
                progress.milestones.append(
                    Milestone(timestamp=elapsed, label=f"{skill_name} invoked")
                )

            # TodoWrite → update tasks
            if name == "TodoWrite":
                todos = inp.get("todos", [])
                if isinstance(todos, list):
                    for todo in todos:
                        if isinstance(todo, dict):
                            subject = todo.get("content", "")
                            status = todo.get("status", "pending")
                            if subject:
                                progress.tasks[subject] = status

            # GH Actions collapsible group
            if progress_adapter is not None:
                progress_adapter.on_group_open(f"Tool: {name}")
            else:
                print(f"::group::Tool: {name}")  # noqa: T201
            console.log(f"[cyan]Tool:[/cyan] {name}")
            if isinstance(block.input, dict):
                for k, v in block.input.items():
                    line = f"  {k}: {str(v)[:100]}"
                    console.log(f"  [dim]{k}:[/dim] {str(v)[:100]}")
                    if progress_adapter is not None:
                        progress_adapter.on_event("tool_input", line)
            if progress_adapter is not None:
                progress_adapter.on_group_close()
            else:
                print("::endgroup::")  # noqa: T201
        elif isinstance(block, TextBlock):
            if block.text:
                preview = block.text[:200].replace("\n", " ")
                console.log(f"[dim]{preview}[/dim]")


# ── StageRunner implementation ──────────────────────────────────────


class SdkStageRunner:
    """StageRunner backed by the Claude Agent SDK. Wraps ``run_stage``."""

    def __init__(
        self,
        progress: ProgressAdapter | None = None,
        effort: str | None = None,
    ) -> None:
        self._progress = progress
        self._effort = effort

    async def run(
        self,
        user_prompt: str,
        system_prompt: str,
        config: StageConfig,
        ticket_key: str,
        stage: StageName,
        project_root: str,
        is_resume: bool = False,
        on_progress: Callable[[str], None] | None = None,
        branch: str = "",
    ) -> RunResult:
        return await run_stage(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            config=config,
            ticket_key=ticket_key,
            stage=stage,
            project_root=project_root,
            is_resume=is_resume,
            on_progress=on_progress,
            branch=branch,
            progress_adapter=self._progress,
            effort=self._effort,
        )
