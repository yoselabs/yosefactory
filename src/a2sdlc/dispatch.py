"""Dispatch — single entry point for the a2sdlc pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from a2sdlc.adapters.protocols import GitAdapter, StageRunner, TicketAdapter
from a2sdlc.config import ProjectConfig, load_stage_config, resolve_flags
from a2sdlc.exceptions import BlockedError, SkipEvent
from a2sdlc.models import (
    BranchState,
    StageName,
    StageStatus,
    extract_result,
    strip_status_block,
)
from a2sdlc.runner import format_cost
from a2sdlc.stages import next_stage


@dataclass
class DispatchContext:
    """All external dependencies — injected, not constructed."""

    tickets: TicketAdapter
    git: GitAdapter
    runner: StageRunner
    config: ProjectConfig
    project_root: Path
    logger: logging.Logger


@dataclass
class DispatchResult:
    """What happened — for testing and logging."""

    stage: StageName
    status: StageStatus | None = None
    next_stage: StageName | None = None
    blocked: bool = False
    error: str | None = None


async def dispatch(ctx: DispatchContext) -> DispatchResult:
    """Run one pipeline stage. Returns what happened."""
    # 1. Parse event
    try:
        event = ctx.tickets.parse_event()
    except SkipEvent as e:
        ctx.logger.info("dispatch.skip", extra={"reason": e.reason})
        return DispatchResult(stage=StageName.SPEC, error=e.reason)

    ctx.logger.info(
        "dispatch.start",
        extra={"key": event.key, "stage": event.stage.value},
    )

    # 2. Resolve flags
    labels = ctx.tickets.get_labels(event.key)
    flags = resolve_flags(ctx.config.pipeline_flags(), labels)
    ctx.logger.info(
        "dispatch.flags",
        extra={
            "auto_spec": flags.auto_spec,
            "auto_proceed": flags.auto_proceed,
            "auto_merge": flags.auto_merge,
        },
    )

    # 3. Read state + circuit breaker
    state_json = ctx.git.read_state()
    state: BranchState | None = None
    if state_json:
        try:
            state = BranchState.model_validate_json(state_json)
        except Exception:
            ctx.logger.warning("dispatch.state_parse_error", exc_info=True)

    if event.stage == StageName.REVIEW:
        stage_config = load_stage_config(event.stage.value, ctx.config)
        cycles = state.review_cycles if state else 0
        if cycles >= stage_config.max_review_cycles:
            reason = (
                f"Circuit breaker: {cycles} review cycles "
                f"exceeded max ({stage_config.max_review_cycles})"
            )
            ctx.logger.error("dispatch.circuit_breaker", extra={"cycles": cycles})
            ctx.tickets.set_blocked(event.key, reason)
            return DispatchResult(stage=event.stage, blocked=True, error=reason)

    # 4. Git setup
    try:
        base = state.base_branch if state else ctx.config.default_base
        branch = ctx.git.setup_branch(event.key, base)
        ctx.logger.info("dispatch.branch_setup", extra={"branch": branch, "base": base})
    except BlockedError as e:
        ctx.logger.error("dispatch.git_blocked", extra={"reason": e.reason})
        ctx.tickets.set_blocked(event.key, e.reason)
        return DispatchResult(stage=event.stage, blocked=True, error=e.reason)

    # 5. Announce start
    comment_id = ctx.tickets.post_comment(
        event.key, f"⏳ **{event.stage.value}** started..."
    )
    ctx.tickets.set_stage_label(event.key, event.stage)

    # 6. Merge stage — deterministic, no AI
    if event.stage == StageName.MERGE:
        pr = event.pr_number or ctx.tickets.get_pr_for_branch(branch)
        if pr:
            ctx.git.sync_with_base(ctx.config.default_base)
            ctx.tickets.merge_pr(pr)
            ctx.tickets.update_comment(event.key, comment_id, "✅ Merged to main")
            ctx.tickets.set_done_label(event.key)
            ctx.logger.info("dispatch.merged", extra={"pr": pr})
            return DispatchResult(stage=StageName.MERGE)
        reason = f"No PR found for branch {branch}"
        ctx.tickets.update_comment(event.key, comment_id, f"🚨 {reason}")
        ctx.tickets.set_blocked(event.key, reason)
        return DispatchResult(stage=StageName.MERGE, blocked=True, error=reason)

    # 7. Load stage config
    stage_config = load_stage_config(event.stage.value, ctx.config)

    # 8. Assemble prompt
    ticket_context = ctx.tickets.get_ticket(event.key)
    from a2sdlc.cli import assemble_system_prompt  # noqa: PLC0415

    system_prompt = assemble_system_prompt(
        event.stage.value, ctx.project_root / ".a2sdlc"
    )

    # 9. Auto-spec prompt prefix
    if flags.auto_spec and event.stage == StageName.SPEC:
        system_prompt = (
            "IMPORTANT: Make your best judgment for all ambiguous requirements. "
            "Do not ask questions — produce the spec directly.\n\n" + system_prompt
        )

    # 10. Run stage
    def on_progress(text: str) -> None:
        try:
            ctx.tickets.update_comment(event.key, comment_id, text)
        except Exception:  # noqa: BLE001
            ctx.logger.warning("dispatch.progress_update_failed", exc_info=True)

    result = await ctx.runner.run(
        user_prompt=ticket_context,
        system_prompt=system_prompt,
        config=stage_config,
        ticket_key=event.key,
        stage=event.stage,
        project_root=str(ctx.project_root),
        is_resume=event.is_resume,
        on_progress=on_progress,
    )

    ctx.logger.info(
        "dispatch.stage_complete",
        extra={
            "stage": event.stage.value,
            "success": result.success,
            "cost_usd": result.total_cost_usd,
            "duration_ms": result.duration_ms,
            "tokens_in": result.input_tokens,
            "tokens_out": result.output_tokens,
        },
    )

    # 11. Handle failure
    cost_footer = format_cost(result)
    if not result.success:
        error_msg = (
            f"🚨 **{event.stage.value}** failed: `{result.error}`\n\n{cost_footer}"
        )
        ctx.tickets.update_comment(event.key, comment_id, error_msg)
        ctx.tickets.set_blocked(event.key, result.error or "unknown")
        return DispatchResult(stage=event.stage, blocked=True, error=result.error)

    # 12. Parse result
    stage_result = extract_result(result.output)
    if stage_result is None:
        partial = result.output[:2000]
        error_msg = (
            f"⚠️ No status block in **{event.stage.value}** output."
            f"\n\n{partial}\n\n{cost_footer}"
        )
        ctx.tickets.update_comment(event.key, comment_id, error_msg)
        ctx.tickets.set_blocked(event.key, "no status block in output")
        return DispatchResult(stage=event.stage, blocked=True, error="no_status_block")

    comment_body = strip_status_block(result.output)
    ctx.tickets.update_comment(
        event.key, comment_id, f"{comment_body}\n\n{cost_footer}"
    )

    # 13. Side effects — PR review
    if event.stage == StageName.REVIEW and event.pr_number:
        review_event = (
            "APPROVE"
            if stage_result.status == StageStatus.APPROVED
            else "REQUEST_CHANGES"
        )
        ctx.tickets.post_review(event.pr_number, comment_body, review_event)

    # 14. Write state + commit + push
    review_cycles = state.review_cycles if state else 0
    if stage_result.status == StageStatus.CHANGES_REQUESTED:
        review_cycles += 1
    new_state = BranchState(
        stage=event.stage,
        status=stage_result.status,
        base_branch=state.base_branch if state else ctx.config.default_base,
        review_cycles=review_cycles,
        last_updated=datetime.now(timezone.utc).isoformat(),
    )
    ctx.git.write_state(new_state.model_dump_json(indent=2))
    ctx.git.commit_artifacts("chore: stage artifacts", [".a2sdlc/state.json"])
    ctx.git.push()

    # 15. Transition
    next_st = next_stage(event.stage, stage_result.status, flags)

    ctx.logger.info(
        "dispatch.transition",
        extra={
            "from": event.stage.value,
            "status": stage_result.status.value,
            "to": next_st.value if next_st else None,
        },
    )

    if next_st is not None:
        ctx.tickets.set_stage_label(event.key, next_st)

    # 16. Return
    return DispatchResult(
        stage=event.stage,
        status=stage_result.status,
        next_stage=next_st,
        blocked=False,
    )
