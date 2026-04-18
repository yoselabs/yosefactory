"""Runner — Claude Agent SDK wrapper with progress_state emission."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    ToolUseBlock,
)

from a2sdlc.config import StageConfig, get_session_id
from a2sdlc.domain.models import StageName
from a2sdlc.domain.run_result import RunResult
from a2sdlc.evaluation.progress import ProgressState, extract_target

logger = logging.getLogger("a2sdlc.pipeline.runner")

# Maps a2sdlc's ``effort`` config to the SDK's ``ClaudeAgentOptions.effort``.
_EFFORT_SDK_MAP: dict[str, str] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "max",
}


async def run_stage(
    user_prompt: str,
    system_prompt: str,
    config: StageConfig,
    ticket_key: str,
    stage: str,
    project_root: str,
    progress_state: ProgressState,
    is_resume: bool = False,
    branch: str = "",
    effort: str | None = None,
) -> RunResult:
    """Run a pipeline stage via Claude Agent SDK; mutates progress_state."""
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

    timeout_seconds = config.timeout_minutes * 60
    result_msg: ResultMessage | None = None

    try:

        async def _stream() -> None:
            nonlocal result_msg
            num_turns = 0
            async for msg in query(prompt=user_prompt, options=options):
                if isinstance(msg, AssistantMessage):
                    num_turns += 1
                    await _handle_assistant_message(msg, progress_state, num_turns)
                elif isinstance(msg, ResultMessage):
                    result_msg = msg

        await asyncio.wait_for(_stream(), timeout=timeout_seconds)
    except TimeoutError:
        logger.error(
            "Stage %s timed out after %d minutes",
            stage,
            config.timeout_minutes,
        )
        return RunResult(
            success=False,
            error=f"timeout ({config.timeout_minutes}min)",
            session_id=sid,
            tool_log=[e.name for e in progress_state.tool_log],
            progress=progress_state,
        )
    except Exception as exc:
        logger.exception("SDK error during stage %s", stage)
        return RunResult(
            success=False,
            error=f"sdk_error: {type(exc).__name__}: {exc}",
            session_id=sid,
            tool_log=[e.name for e in progress_state.tool_log],
            progress=progress_state,
        )

    if result_msg is None:
        return RunResult(
            success=False,
            error="no_result",
            session_id=sid,
            tool_log=[e.name for e in progress_state.tool_log],
            progress=progress_state,
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
        tool_log=[e.name for e in progress_state.tool_log],
        progress=progress_state,
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


async def _handle_assistant_message(
    msg: object,
    progress_state: ProgressState,
    num_turns: int,
) -> None:
    """Extract tool calls, usage, and milestones from an AssistantMessage.

    ``num_turns`` is owned by the runner loop (incremented once per
    AssistantMessage there) and threaded in. The handler must not
    increment it — doing so would double-count.
    """
    # Update token/cost from usage when SDK provides it; emit Metrics on
    # every assistant message so subscribers see live num_turns + elapsed
    # even when this particular message has no usage payload.
    usage = getattr(msg, "usage", None)
    if usage:
        progress_state.input_tokens = _get_tokens(usage, "input_tokens")
        progress_state.output_tokens = _get_tokens(usage, "output_tokens")
    cost = getattr(msg, "total_cost_usd", None)
    if cost:
        progress_state.total_cost_usd = cost
    await progress_state.update_metrics(
        tin=progress_state.input_tokens,
        tout=progress_state.output_tokens,
        cost=progress_state.total_cost_usd,
        turns=num_turns,
    )

    # Process content blocks
    content = getattr(msg, "content", None)
    if not content:
        return
    for block in content:
        if isinstance(block, ToolUseBlock):
            name = block.name or "unknown"
            inp = block.input if isinstance(block.input, dict) else {}
            target = extract_target(name, inp, progress_state.project_root)
            await progress_state.add_tool_call(name, target)

            # Skill invocation → milestone
            if name == "Skill":
                skill_name = inp.get("skill", "unknown")
                await progress_state.add_milestone(f"{skill_name} invoked")

            # TodoWrite → update tasks dict (no event needed)
            if name == "TodoWrite":
                todos = inp.get("todos", [])
                if isinstance(todos, list):
                    for todo in todos:
                        if isinstance(todo, dict):
                            subject = todo.get("content", "")
                            status = todo.get("status", "pending")
                            if subject:
                                progress_state.tasks[subject] = status
        # TextBlock dropped — logging covers it.


# ── StageRunner implementation ──────────────────────────────────────


class SdkStageRunner:
    """StageRunner backed by the Claude Agent SDK. Wraps ``run_stage``."""

    def __init__(self, effort: str | None = None) -> None:
        self._effort = effort

    async def run(
        self,
        user_prompt: str,
        system_prompt: str,
        config: StageConfig,
        ticket_key: str,
        stage: StageName,
        project_root: str,
        progress_state: ProgressState,
        is_resume: bool = False,
        branch: str = "",
    ) -> RunResult:
        return await run_stage(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            config=config,
            ticket_key=ticket_key,
            stage=stage,
            project_root=project_root,
            progress_state=progress_state,
            is_resume=is_resume,
            branch=branch,
            effort=self._effort,
        )
