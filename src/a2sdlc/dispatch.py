"""Dispatch v2 — thin orchestrator composing v2 modules."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from a2sdlc.adapters.protocols import GitAdapter, StageRunner
from a2sdlc.adapters.review import ReviewAdapter
from a2sdlc.adapters.work import WorkAdapter
from a2sdlc.comment_lifecycle import CommentManager
from a2sdlc.config import ProjectConfig, load_stage_config
from a2sdlc.directives import parse_directives
from a2sdlc.exceptions import BlockedError, SkipEvent
from a2sdlc.models import (
    GateConfig,
    GateMode,
    StageName,
    StageStatus,
    TicketState,
    strip_status_block,
)
from a2sdlc.pr_lifecycle import PRLifecycle
from a2sdlc.progress import format_error, format_final
from a2sdlc.runner import RunResult
from a2sdlc.stage_executor import StageExecutor
from a2sdlc.stages import next_stage
from a2sdlc.state_manager import StateManager


@dataclass
class DispatchContext:
    """All external dependencies — injected, not constructed."""

    work: WorkAdapter
    git: GitAdapter
    review: ReviewAdapter
    runner: StageRunner
    config: ProjectConfig
    project_root: Path
    logger: logging.Logger
    run_id: str | None = None


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
        event = ctx.work.parse_event()
    except SkipEvent as e:
        ctx.logger.info("dispatch.skip", extra={"reason": e.reason})
        return DispatchResult(stage=StageName.SPEC, error=e.reason)

    ctx.logger.info(
        "dispatch.start",
        extra={"key": event.key, "stage": event.stage.value},
    )

    # 2. Parse ticket directives + build gate config
    ticket_body = ctx.work.get_ticket(event.key)
    directives, clean_body = parse_directives(ticket_body)

    gates = ctx.config.gate_config()
    if directives.gate_merge is not None:
        gates = GateConfig(merge=directives.gate_merge, review=gates.review)
    if directives.gate_review is not None:
        gates = GateConfig(merge=gates.merge, review=directives.gate_review)

    auto_spec = ctx.config.auto_spec

    # 3. Read state + idempotency check
    state_mgr = StateManager(ctx.git)
    state = state_mgr.read_state()

    if ctx.run_id and state_mgr.check_idempotency(ctx.run_id):
        ctx.logger.info("dispatch.duplicate_run_id", extra={"run_id": ctx.run_id})
        return DispatchResult(stage=event.stage, error="duplicate_run_id")

    # 4. Circuit breaker for review stage
    if event.stage == StageName.REVIEW:
        stage_config = load_stage_config(event.stage.value, ctx.config)
        cycles = state.review_cycles if state else 0
        if cycles >= stage_config.max_review_cycles:
            reason = (
                f"Circuit breaker: {cycles} review cycles "
                f"exceeded max ({stage_config.max_review_cycles})"
            )
            ctx.logger.error("dispatch.circuit_breaker", extra={"cycles": cycles})
            ctx.work.set_blocked(event.key, reason)
            return DispatchResult(stage=event.stage, blocked=True, error=reason)

    # 5. Branch setup
    base = directives.base or (state.base_branch if state else ctx.config.default_base)
    branch = ctx.work.format_branch(event.key)
    try:
        ctx.git.setup_branch(branch, base)
        ctx.logger.info("dispatch.branch_setup", extra={"branch": branch, "base": base})
    except BlockedError as e:
        ctx.logger.error("dispatch.git_blocked", extra={"reason": e.reason})
        ctx.work.set_blocked(event.key, e.reason)
        return DispatchResult(stage=event.stage, blocked=True, error=e.reason)

    # 6. Draft PR creation (on spec stage if no PR exists yet)
    pr_lifecycle = PRLifecycle(ctx.review)
    pr_number = state.pr_number if state else None
    if event.stage == StageName.SPEC and pr_number is None:
        pr_number = pr_lifecycle.create_draft(branch, base, event.key)
        ctx.logger.info("dispatch.draft_pr_created", extra={"pr": pr_number})

    if event.pr_number is not None:
        pr_number = event.pr_number

    # 7. Start comment
    comment = CommentManager(ctx.work, event.key)
    comment.start(event.stage.value)

    # 8. Merge stage — deterministic, no AI
    if event.stage == StageName.MERGE:
        if pr_number is None:
            reason = f"No PR found for branch {branch}"
            comment.finalize(f"\U0001f6a8 {reason}")
            ctx.work.set_blocked(event.key, reason)
            return DispatchResult(stage=StageName.MERGE, blocked=True, error=reason)

        if gates.merge == GateMode.HUMAN:
            if not pr_lifecycle.check_human_approval(pr_number):
                comment.finalize("\u23f3 Waiting for human approval before merge.")
                return DispatchResult(
                    stage=StageName.MERGE, blocked=True, error="waiting_for_approval"
                )

        ctx.git.sync_with_base(base)
        pr_lifecycle.merge(pr_number)
        comment.finalize("\u2705 Merged")
        ctx.work.set_done_label(event.key)
        ctx.logger.info("dispatch.merged", extra={"pr": pr_number})
        return DispatchResult(stage=StageName.MERGE)

    # 9. Load stage config + assemble prompts
    stage_config = load_stage_config(event.stage.value, ctx.config)

    from a2sdlc.cli import assemble_system_prompt  # noqa: PLC0415

    system_prompt = assemble_system_prompt(
        event.stage.value, ctx.project_root / ".a2sdlc"
    )

    if auto_spec and event.stage == StageName.SPEC:
        system_prompt = (
            "IMPORTANT: Make your best judgment for all ambiguous requirements. "
            "Do not ask questions \u2014 produce the spec directly.\n\n" + system_prompt
        )

    # 10. Build user prompt
    user_prompt = clean_body
    if event.stage == StageName.REVIEW and pr_number is not None:
        pr_context = pr_lifecycle.read_context(pr_number)
        user_prompt = f"{clean_body}\n\n{pr_context}"

    # 11. Execute stage
    executor = StageExecutor(ctx.runner)
    exec_result = await executor.run(
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        config=stage_config,
        ticket_key=event.key,
        stage=event.stage,
        project_root=str(ctx.project_root),
        is_resume=event.is_resume,
        on_progress=lambda text: comment.update(text),
        branch=branch,
    )

    stage_result = exec_result.stage_result

    # 12. Log full output to CI
    print(f"::group::Agent output ({len(exec_result.output)} chars)")  # noqa: T201
    print(exec_result.output)  # noqa: T201
    print("::endgroup::")  # noqa: T201

    # Build shared format kwargs
    _milestones = exec_result.milestones
    _ctx_window = exec_result.progress.context_window if exec_result.progress else None

    # Helper: commit and push
    def _commit_and_push() -> None:
        try:
            ctx.git.commit_artifacts("chore: stage artifacts", [".a2sdlc/", "docs/"])
            ctx.git.push()
        except Exception:  # noqa: BLE001
            ctx.logger.warning("dispatch.commit_push_failed", exc_info=True)

    # 13. Handle failure
    if not exec_result.success:
        error_result = RunResult(
            success=False,
            error=exec_result.error,
            input_tokens=exec_result.stats.tokens_in,
            output_tokens=exec_result.stats.tokens_out,
            total_cost_usd=exec_result.stats.cost_usd,
            duration_ms=exec_result.stats.duration_ms,
            num_turns=exec_result.stats.num_turns,
        )
        error_comment = format_error(
            error_result,
            stage=event.stage.value,
            milestones=_milestones,
            model=stage_config.model,
            branch=branch,
            max_turns=stage_config.max_turns,
            context_window=_ctx_window,
        )
        comment.finalize(error_comment)
        _commit_and_push()
        ctx.work.set_blocked(event.key, exec_result.error or "unknown")
        return DispatchResult(stage=event.stage, blocked=True, error=exec_result.error)

    # 14. No status block even after follow-ups
    if stage_result is None:
        partial = exec_result.output[:2000]
        fallback_result = RunResult(
            success=True,
            output=partial,
            input_tokens=exec_result.stats.tokens_in,
            output_tokens=exec_result.stats.tokens_out,
            total_cost_usd=exec_result.stats.cost_usd,
            duration_ms=exec_result.stats.duration_ms,
            num_turns=exec_result.stats.num_turns,
        )
        no_status_footer = format_final(
            fallback_result,
            stage=event.stage.value,
            milestones=_milestones,
            model=stage_config.model,
            branch=branch,
            max_turns=stage_config.max_turns,
            context_window=_ctx_window,
        )
        error_msg = (
            f"\u26a0\ufe0f No status block in **{event.stage.value}** output."
            f"\n\n{partial}\n\n{no_status_footer}"
        )
        comment.finalize(error_msg)
        _commit_and_push()
        ctx.work.set_blocked(event.key, "no status block in output")
        return DispatchResult(stage=event.stage, blocked=True, error="no_status_block")

    # 15. Success path
    comment_body = strip_status_block(exec_result.output)
    stats_result = RunResult(
        success=True,
        output=comment_body,
        input_tokens=exec_result.stats.tokens_in,
        output_tokens=exec_result.stats.tokens_out,
        total_cost_usd=exec_result.stats.cost_usd,
        duration_ms=exec_result.stats.duration_ms,
        num_turns=exec_result.stats.num_turns,
    )
    _tasks = exec_result.progress.tasks if exec_result.progress else None
    final_comment = format_final(
        stats_result,
        stage=event.stage.value,
        milestones=_milestones,
        model=stage_config.model,
        branch=branch,
        max_turns=stage_config.max_turns,
        context_window=_ctx_window,
        tasks=_tasks,
    )
    comment.finalize(final_comment)

    # Side effects
    if event.stage == StageName.REVIEW and pr_number is not None:
        verdict = (
            "APPROVE"
            if stage_result.status == StageStatus.APPROVED
            else "REQUEST_CHANGES"
        )
        pr_lifecycle.post_review(pr_number, comment_body, verdict)

    if (
        event.stage == StageName.IMPLEMENT
        and stage_result.status == StageStatus.COMPLETE
        and pr_number is not None
    ):
        pr_lifecycle.update_from_result(pr_number, stage_result, event.key)

    # 16. Write state
    review_cycles = state.review_cycles if state else 0
    if stage_result.status == StageStatus.CHANGES_REQUESTED:
        review_cycles += 1
    new_state = TicketState(
        stage=event.stage,
        status=stage_result.status,
        base_branch=base,
        branch=branch,
        pr_number=pr_number,
        stage_run_id=ctx.run_id or "",
        review_cycles=review_cycles,
        accumulated_cost_usd=exec_result.stats.cost_usd,
        accumulated_tokens_in=exec_result.stats.tokens_in,
        accumulated_tokens_out=exec_result.stats.tokens_out,
        accumulated_duration_ms=exec_result.stats.duration_ms,
        last_updated=datetime.now(timezone.utc).isoformat(),
    )
    state_mgr.write_state(new_state)
    _commit_and_push()

    # 17. Transition
    next_st = next_stage(event.stage, stage_result.status, gates)

    ctx.logger.info(
        "dispatch.transition",
        extra={
            "from": event.stage.value,
            "status": stage_result.status.value,
            "to": next_st.value if next_st else None,
        },
    )

    if next_st is not None:
        ctx.work.set_stage_label(event.key, next_st)

    return DispatchResult(
        stage=event.stage,
        status=stage_result.status,
        next_stage=next_st,
        blocked=False,
    )
