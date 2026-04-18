"""Dispatch v2 — thin orchestrator composing v2 modules."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from a2sdlc.adapters.protocols import GitAdapter, StageRunner
from a2sdlc.adapters.review import ReviewAdapter
from a2sdlc.adapters.work import WorkAdapter
from a2sdlc.lifecycle.comment import CommentManager
from a2sdlc.config import ProjectConfig, get_session_id, load_stage_config
from a2sdlc.pipeline.context import assemble_context, pick_handover
from a2sdlc.domain.directives import parse_directives
from a2sdlc.domain.exceptions import BlockedError, SkipEvent
from a2sdlc.pipeline.feedback_routing import resolve_target_stage
from a2sdlc.domain.models import (
    GateConfig,
    GateMode,
    StageName,
    StageStatus,
    TicketState,
    strip_status_block,
)
from a2sdlc.lifecycle.pr import PRLifecycle
from a2sdlc.evaluation.progress import (
    ProgressState,
    context_window_for_model,
    format_error,
    format_final,
)
from a2sdlc.evaluation.stats import StageRunStats
from a2sdlc.assembly.prompt import assemble_system_prompt
from a2sdlc.pipeline.stage_executor import StageExecutor
from a2sdlc.stages import next_stage
from a2sdlc.lifecycle.state import StateManager


@dataclass
class DispatchContext:
    """All external dependencies — injected, not constructed."""

    work: WorkAdapter
    git: GitAdapter
    review: ReviewAdapter
    runner: StageRunner
    progress_state: ProgressState
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
    # Cost/token telemetry from the stage run (only populated on success path).
    stats: StageRunStats | None = None


async def dispatch(ctx: DispatchContext) -> DispatchResult:
    """Run one pipeline stage. Returns what happened."""
    # 1. Parse event
    try:
        event = ctx.work.parse_event()
    except SkipEvent as e:
        ctx.logger.info("dispatch.skip", extra={"reason": e.reason})
        return DispatchResult(stage=StageName.SPEC, error=e.reason)

    # 2. Shared setup: ticket body + directives
    ticket_body = ctx.work.get_ticket(event.key)
    directives, clean_body = parse_directives(ticket_body)

    # ── Route: feedback / proceed / label ──────────────────────
    user_prompt_override: str | None = None

    if event.is_feedback:
        # Collect handovers from both issue and PR
        issue_handover = ctx.work.find_last_handover(event.key)
        pr_handover = None
        pr_diff = None
        if event.pr_number:
            pr_handover = ctx.review.find_last_handover(event.pr_number)
            pr_diff = ctx.review.read_pr_diff(event.pr_number)

        handover = pick_handover(issue_handover, pr_handover)
        since = handover.created_at if handover else datetime.min

        context = assemble_context(
            ticket_body=clean_body,
            issue_handover=issue_handover,
            pr_handover=pr_handover,
            issue_feedback=ctx.work.collect_issue_feedback(event.key, since),
            pr_feedback=(
                ctx.review.collect_pr_feedback(event.pr_number, since)
                if event.pr_number
                else []
            ),
            pr_diff=pr_diff,
        )

        # Dedup: skip if handover is newer than all feedback
        if context.feedback and not context.is_first_run:
            newest_feedback = max(f.created_at for f in context.feedback)
            if handover and handover.created_at > newest_feedback:
                ctx.logger.info("dispatch.feedback_already_addressed")
                return DispatchResult(
                    stage=context.current_stage or StageName.SPEC,
                    error="feedback_already_addressed",
                )

        target_stage = resolve_target_stage(context.current_stage)
        user_prompt_override = context.user_prompt

    elif event.trigger_stage is None:
        # Proceed: advance past current gate
        issue_handover = ctx.work.find_last_handover(event.key)
        current_stage = issue_handover.stage if issue_handover else None
        if current_stage == StageName.SPEC:
            target_stage = StageName.IMPLEMENT
        elif current_stage == StageName.REVIEW:
            target_stage = StageName.MERGE
        else:
            target_stage = StageName.IMPLEMENT  # fallback

    else:
        target_stage = event.trigger_stage

    # ── Shared setup continues ────────────────────────────────
    ctx.logger.info(
        "dispatch.start",
        extra={"key": event.key, "stage": target_stage.value},
    )

    gates = ctx.config.gate_config()
    if directives.gate_merge is not None:
        gates = GateConfig(merge=directives.gate_merge, spec=gates.spec)
    if directives.gate_spec is not None:
        gates = GateConfig(merge=gates.merge, spec=directives.gate_spec)

    self_answer = ctx.config.self_answer

    # 3. Read state + idempotency check
    state_mgr = StateManager(ctx.git)
    state = state_mgr.read_state()

    if ctx.run_id and state_mgr.check_idempotency(ctx.run_id):
        ctx.logger.info("dispatch.duplicate_run_id", extra={"run_id": ctx.run_id})
        return DispatchResult(stage=target_stage, error="duplicate_run_id")

    # 4. Circuit breaker for review stage
    if target_stage == StageName.REVIEW:
        _cb_config = load_stage_config(target_stage.value, ctx.config)
        cycles = state.review_cycles if state else 0
        if cycles >= _cb_config.max_review_cycles:
            reason = (
                f"Circuit breaker: {cycles} review cycles "
                f"exceeded max ({_cb_config.max_review_cycles})"
            )
            ctx.logger.error("dispatch.circuit_breaker", extra={"cycles": cycles})
            ctx.work.set_blocked(event.key, reason)
            return DispatchResult(stage=target_stage, blocked=True, error=reason)

    # 5. Branch setup
    base = directives.base or (state.base_branch if state else ctx.config.default_base)
    branch = ctx.work.format_branch(event.key)
    try:
        ctx.git.setup_branch(branch, base)
        ctx.logger.info("dispatch.branch_setup", extra={"branch": branch, "base": base})
    except BlockedError as e:
        ctx.logger.error("dispatch.git_blocked", extra={"reason": e.reason})
        ctx.work.set_blocked(event.key, e.reason)
        return DispatchResult(stage=target_stage, blocked=True, error=e.reason)

    # 6. Draft PR creation (on spec stage if no PR exists yet)
    pr_lifecycle = PRLifecycle(ctx.review)
    pr_number = state.pr_number if state else None
    if target_stage == StageName.SPEC and pr_number is None:
        pr_number = pr_lifecycle.create_draft(branch, base, event.key)
        ctx.logger.info("dispatch.draft_pr_created", extra={"pr": pr_number})

    if event.pr_number is not None:
        pr_number = event.pr_number

    # 7. Start comment
    comment = CommentManager(ctx.work, event.key)
    comment.start(target_stage.value)

    # Register the comment-driving subscriber now that we have a comment handle.
    # This is the one place dispatch.py knows about a specific subscriber, because
    # the comment lifecycle is intrinsically dispatch-scoped.
    from a2sdlc.adapters.gh_comment_subscriber import GhCommentSubscriber  # noqa: PLC0415

    ctx.progress_state.subscribe(GhCommentSubscriber(comment, ctx.progress_state))

    # 7.5 Load stage config early so stage_start has model/max_turns even for MERGE.
    stage_config = load_stage_config(target_stage.value, ctx.config)
    session_id = ctx.run_id or get_session_id(event.key, target_stage.value)

    await ctx.progress_state.stage_start(
        target_stage,
        session_id,
        model=stage_config.model,
        max_turns=stage_config.max_turns,
        context_window=context_window_for_model(stage_config.model) or 0,
        branch=branch,
    )

    # Initialize success/error trackers BEFORE the try block. Default error to
    # "unknown" so an unhandled crash produces an informative StageEnd payload.
    _stage_success: bool = False
    _stage_error: str | None = "unknown"

    try:
        # 8. Merge stage — deterministic, no AI
        if target_stage == StageName.MERGE:
            if pr_number is None:
                reason = f"No PR found for branch {branch}"
                comment.finalize(f"\U0001f6a8 {reason}")
                ctx.work.set_blocked(event.key, reason)
                _stage_error = reason
                return DispatchResult(stage=StageName.MERGE, blocked=True, error=reason)

            if gates.merge == GateMode.HUMAN:
                if not pr_lifecycle.check_human_approval(pr_number):
                    comment.finalize("\u23f3 Waiting for human approval before merge.")
                    _stage_error = "waiting_for_approval"
                    return DispatchResult(
                        stage=StageName.MERGE,
                        blocked=True,
                        error="waiting_for_approval",
                    )

            ctx.git.sync_with_base(base)
            pr_lifecycle.merge(pr_number)
            comment.finalize("\u2705 Merged")
            ctx.work.set_done_label(event.key)
            ctx.logger.info("dispatch.merged", extra={"pr": pr_number})
            _stage_success = True
            _stage_error = None
            return DispatchResult(stage=StageName.MERGE)

        # 9. Assemble prompts (stage_config already loaded above)
        system_prompt = assemble_system_prompt(
            target_stage.value, ctx.project_root / ".a2sdlc"
        )

        if event.is_feedback:
            system_prompt = (
                "IMPORTANT: You are addressing feedback on your previous work. "
                "Focus on the feedback items below.\n\n" + system_prompt
            )

        if self_answer and target_stage == StageName.SPEC:
            system_prompt = (
                "IMPORTANT: Make your best judgment for all ambiguous requirements. "
                "Do not ask questions \u2014 produce the spec directly.\n\n"
                + system_prompt
            )

        # 10. Build user prompt
        if user_prompt_override is not None:
            user_prompt = user_prompt_override
        else:
            user_prompt = clean_body
            if target_stage == StageName.REVIEW and pr_number is not None:
                pr_context = pr_lifecycle.read_context(pr_number)
                user_prompt = f"{clean_body}\n\n{pr_context}"

        # 11. Execute stage
        executor = StageExecutor(ctx.runner)
        exec_result = await executor.run(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            config=stage_config,
            ticket_key=event.key,
            stage=target_stage,
            project_root=str(ctx.project_root),
            progress_state=ctx.progress_state,
            is_resume=False,
            branch=branch,
        )

        stage_result = exec_result.stage_result

        # 12. Log full output to CI (logging only — no progress event;
        # an empty GroupOpen/GroupClose pair would render as a foldable
        # block with nothing inside).
        ctx.logger.info("agent.output", extra={"len": len(exec_result.output)})

        # Build shared format kwargs
        _milestones = exec_result.milestones
        _ctx_window = (
            exec_result.progress.context_window if exec_result.progress else None
        )

        # Helper: commit and push
        def _commit_and_push() -> None:
            try:
                ctx.git.commit_artifacts(
                    "chore: stage artifacts", [".a2sdlc/", "docs/"]
                )
                ctx.git.push()
            except Exception:  # noqa: BLE001
                ctx.logger.warning("dispatch.commit_push_failed", exc_info=True)

        # 13. Handle failure
        if not exec_result.success:
            error_comment = format_error(
                exec_result.error or "unknown",
                stage=target_stage.value,
                stats=exec_result.stats,
                milestones=_milestones,
                model=stage_config.model,
                branch=branch,
                max_turns=stage_config.max_turns,
                context_window=_ctx_window,
            )
            comment.finalize(error_comment)
            _commit_and_push()
            ctx.work.set_blocked(event.key, exec_result.error or "unknown")
            _stage_error = exec_result.error or "unknown"
            return DispatchResult(
                stage=target_stage, blocked=True, error=exec_result.error
            )

        # 14. No status block even after follow-ups
        if stage_result is None:
            partial = exec_result.output[:2000]
            no_status_footer = format_final(
                partial,
                stage=target_stage.value,
                stats=exec_result.stats,
                milestones=_milestones,
                model=stage_config.model,
                branch=branch,
                max_turns=stage_config.max_turns,
                context_window=_ctx_window,
            )
            error_msg = (
                f"\u26a0\ufe0f No status block in **{target_stage.value}** output."
                f"\n\n{partial}\n\n{no_status_footer}"
            )
            comment.finalize(error_msg)
            _commit_and_push()
            ctx.work.set_blocked(event.key, "no status block in output")
            _stage_error = "no_status_block"
            return DispatchResult(
                stage=target_stage, blocked=True, error="no_status_block"
            )

        # 15. Success path
        comment_body = strip_status_block(exec_result.output)
        _tasks = exec_result.progress.tasks if exec_result.progress else None
        final_comment = format_final(
            comment_body,
            stage=target_stage.value,
            stats=exec_result.stats,
            milestones=_milestones,
            model=stage_config.model,
            branch=branch,
            max_turns=stage_config.max_turns,
            context_window=_ctx_window,
            tasks=_tasks,
        )
        comment.finalize(final_comment)

        # Side effects
        if target_stage == StageName.REVIEW and pr_number is not None:
            verdict = (
                "APPROVE"
                if stage_result.status == StageStatus.APPROVED
                else "REQUEST_CHANGES"
            )
            pr_lifecycle.post_review(pr_number, comment_body, verdict)

        # 16. Write state
        review_cycles = state.review_cycles if state else 0
        if stage_result.status == StageStatus.CHANGES_REQUESTED:
            review_cycles += 1
        new_state = TicketState(
            stage=target_stage,
            status=stage_result.status,
            base_branch=base,
            branch=branch,
            pr_number=pr_number,
            stage_run_id=ctx.run_id or "",
            review_cycles=review_cycles,
            accumulated_cost_usd=(state.accumulated_cost_usd if state else 0.0)
            + exec_result.stats.cost_usd,
            accumulated_tokens_in=(state.accumulated_tokens_in if state else 0)
            + exec_result.stats.tokens_in,
            accumulated_tokens_out=(state.accumulated_tokens_out if state else 0)
            + exec_result.stats.tokens_out,
            accumulated_duration_ms=(state.accumulated_duration_ms if state else 0)
            + exec_result.stats.duration_ms,
            last_updated=datetime.now(timezone.utc).isoformat(),
        )
        state_mgr.write_state(new_state)
        _commit_and_push()

        # 17. Transition
        next_st = next_stage(target_stage, stage_result.status, gates)

        ctx.logger.info(
            "dispatch.transition",
            extra={
                "from": target_stage.value,
                "status": stage_result.status.value,
                "to": next_st.value if next_st else None,
            },
        )

        if next_st is not None:
            ctx.work.set_stage_label(event.key, next_st)

        _stage_success = True
        _stage_error = None
        return DispatchResult(
            stage=target_stage,
            status=stage_result.status,
            next_stage=next_st,
            blocked=False,
            stats=exec_result.stats,
        )

    finally:
        # Emit StageEnd unconditionally for whichever path we took.
        await ctx.progress_state.stage_end(
            target_stage,
            success=_stage_success,
            error=_stage_error,
            final=ctx.progress_state.snapshot_metrics(),
        )
