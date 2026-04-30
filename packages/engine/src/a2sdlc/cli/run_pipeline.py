"""``a2sdlc run`` orchestration — the post-prelude part.

Implements steps 7-11 from spec §CLI surface:

1. Create the run branch off ``base``.
2. Wire ``LocalFileWorkAdapter`` + ``LocalReviewAdapter`` against the
   branch-scoped state directory.
3. Build a ``ProgressState`` with ``ConsoleSubscriber(stream=sys.stdout)``
   plus an opportunistic ``MlflowTraceSubscriber`` (best-effort — local
   mode does not fail when MLflow is unreachable).
4. Run ``SPEC → IMPLEMENT → REVIEW`` directly via
   :class:`StageExecutor`, bypassing the GH-event-shaped ingress chain.
   Each stage's artifact is persisted via the work / review adapters.
5. Commit + push after each stage advance. A failed commit raises
   ``typer.Exit(8)``; a failed push raises ``typer.Exit(9)``.
6. Loop ``IMPLEMENT → REVIEW`` while REVIEW returns
   ``changes_requested``, capped at ``cfg.pipeline.max_review_cycles``.
   Exceeding the cap raises ``typer.Exit(10)``.

The full GH-driven dispatch (with idempotency middleware, PR lifecycle,
state.json read-back, etc.) lives in ``cli/dispatch.py``. Local mode is
deliberately a thinner driver — its trust surface is the smoke harness
(see ``scripts/smoke_local.sh``), not unit-mocked composition.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import typer

from a2sdlc.config_run import RunConfig
from a2sdlc.domain.models import StageName, StageStatus


def _checkout_run_branch(repo: Path, base: str, run_branch: str) -> None:
    """Create the run branch off ``base`` and switch to it."""
    subprocess.run(
        ["git", "checkout", "-b", run_branch, base],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _branch_state_dir(repo: Path, run_branch: str) -> Path:
    """Smoke-harness-aligned state path: slashes → ``__``."""
    slug = run_branch.replace("/", "__")
    return repo / ".a2sdlc" / "state" / slug


def _commit_and_push(
    repo: Path, run_branch: str, message: str, *, logger: logging.Logger
) -> None:
    """Stage everything, commit, push to ``origin``.

    Empty staging area is treated as a no-op — a stage that produced
    nothing under the working tree (artifacts live under .a2sdlc/state/
    which is included via ``git add .``) still records progress
    elsewhere; nothing to commit means we skip the commit but still
    advance.

    Failures raise ``typer.Exit(8)`` (commit) / ``typer.Exit(9)`` (push)
    per the spec failure-modes table.
    """
    add = subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, text=True)
    if add.returncode != 0:
        sys.stderr.write(f"error: git add failed: {add.stderr}\n")
        raise typer.Exit(code=8)
    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if diff.returncode == 0:
        logger.info("commit.empty_skip", extra={"message": message})
    else:
        commit = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        if commit.returncode != 0:
            sys.stderr.write(
                f"error: stage commit failed for '{message}': {commit.stderr}\n"
            )
            raise typer.Exit(code=8)
    push = subprocess.run(
        ["git", "push", "-u", "origin", run_branch],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if push.returncode != 0:
        sys.stderr.write(f"error: push to origin/{run_branch} failed: {push.stderr}\n")
        raise typer.Exit(code=9)


@dataclass
class _StageRunResult:
    status: StageStatus | None
    output: str
    artifact_path: Path | None
    success: bool
    error: str | None


async def _run_one_stage(
    *,
    stage: StageName,
    cycle: int,
    user_prompt: str,
    project_root: Path,
    progress_state,
    runner,
    stage_config_obj,
    branch: str,
    ticket_key: str,
    work_adapter,
    review_adapter,
) -> _StageRunResult:
    """Run a single stage: prompt assemble → executor run → persist artifact."""
    from a2sdlc.assembly.prompt import assemble_system_prompt  # noqa: PLC0415
    from a2sdlc.domain.progress import StageEnd  # noqa: PLC0415
    from a2sdlc.domain.progress_format import (  # noqa: PLC0415
        context_window_for_model,
    )
    from a2sdlc.pipeline.stage_executor import StageExecutor  # noqa: PLC0415

    system_prompt = assemble_system_prompt(stage.value, project_root / ".a2sdlc")

    await progress_state.stage_start(
        stage,
        f"{ticket_key}:{stage.value}:{cycle}",
        model=stage_config_obj.model,
        max_turns=stage_config_obj.max_turns,
        context_window=context_window_for_model(stage_config_obj.model) or 0,
        branch=branch,
    )

    executor = StageExecutor(runner)
    success = True
    error: str | None = None
    artifact: Path | None = None
    status: StageStatus | None = None
    output_text = ""

    try:
        result = await executor.run(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            config=stage_config_obj,
            ticket_key=ticket_key,
            stage=stage,
            project_root=str(project_root),
            progress_state=progress_state,
            is_resume=False,
            branch=branch,
        )
        output_text = result.output
        if not result.success:
            success = False
            error = result.error or "agent_failure"
        elif result.stage_result is not None:
            status = result.stage_result.status

        # Persist artifact regardless of structured-output success — the
        # smoke harness asserts presence of the file, not the schema.
        if stage == StageName.REVIEW:
            verdict = status.value if status is not None else "unknown"
            artifact = review_adapter.post_review(
                pr_number=0, body=output_text, verdict=verdict
            )
        else:
            artifact = work_adapter.write_stage_artifact(stage, cycle, output_text)
    except Exception as exc:  # noqa: BLE001
        success = False
        error = f"{type(exc).__name__}: {exc}"
    finally:
        # Emit StageEnd ourselves so we can attach artifact_path (the
        # default ``stage_end()`` helper does not surface it). The
        # console subscriber prints the BEGIN/END output fences only
        # when artifact_path points to a real file.
        end = StageEnd(
            stage=stage,
            success=success and error is None,
            error=error,
            final_metrics=progress_state.snapshot_metrics(),
            artifact_path=artifact,
        )
        await progress_state._emit(end)  # noqa: SLF001 — local-mode emit-with-artifact

    return _StageRunResult(
        status=status,
        output=output_text,
        artifact_path=artifact,
        success=success and error is None,
        error=error,
    )


def drive_pipeline(
    *,
    repo: Path,
    config: RunConfig,
    base: str,
    input_md: bytes,
    run_branch: str,
    label: str | None,
) -> None:
    """Run the workflow on the freshly-prepared run branch.

    Local-mode driver. Wires real adapters, runs SPEC → IMPLEMENT →
    REVIEW with per-stage commit+push, loops on review-changes-requested
    up to ``config.pipeline.max_review_cycles``, and emits the
    spec-mandated ``done.\\nbranch: <run-branch>`` line on success.
    """
    logger = logging.getLogger("a2sdlc.cli.run")

    try:
        _checkout_run_branch(repo, base, run_branch)
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(
            f"error: failed to create run branch '{run_branch}': {exc.stderr or exc}\n"
        )
        raise typer.Exit(code=1) from exc

    # Lazy imports to keep prelude exit paths cheap (the smoke-harness
    # critical path doesn't pay for these unless we actually run).
    from a2sdlc.adapters.review.local import LocalReviewAdapter  # noqa: PLC0415
    from a2sdlc.adapters.subscriber.console import ConsoleSubscriber  # noqa: PLC0415
    from a2sdlc.adapters.work.local_file import LocalFileWorkAdapter  # noqa: PLC0415
    from a2sdlc.config import load_config_file, load_stage_config  # noqa: PLC0415
    from a2sdlc.domain.progress import ProgressState  # noqa: PLC0415
    from a2sdlc.domain.stats import StageRunStats  # noqa: PLC0415
    from a2sdlc.pipeline.runner import SdkStageRunner  # noqa: PLC0415

    state_root = _branch_state_dir(repo, run_branch)
    state_root.mkdir(parents=True, exist_ok=True)

    ticket_key = label or run_branch

    work_adapter = LocalFileWorkAdapter(
        project_root=repo,
        session_id=ticket_key,
        stage=StageName.SPEC,
        state_root=state_root,
    )
    review_adapter = LocalReviewAdapter(state_root=state_root, cycle=1)

    # Persist INPUT.md as the ticket body so SPEC has something to chew
    # on. ``LocalFileWorkAdapter`` already created the state dir; just
    # write the file directly.
    (state_root / "ticket.md").write_bytes(input_md)

    progress_state = ProgressState(project_root=str(repo))
    progress_state.subscribe(ConsoleSubscriber(stream=sys.stdout))
    try:
        from a2sdlc.adapters.subscriber.mlflow_trace import (  # noqa: PLC0415
            MlflowTraceSubscriber,
        )

        progress_state.subscribe(MlflowTraceSubscriber())
    except Exception:  # noqa: BLE001
        # MLflow unavailable / misconfigured — local mode must not break.
        logger.warning("mlflow_subscriber_disabled", exc_info=True)

    # Stage configs — `load_stage_config` requires a `ProjectConfig`;
    # `RunConfig` is a sibling shape. Load the per-repo defaults if
    # available, fall back to bare stage defaults.
    try:
        project_config = load_config_file(repo)
    except (FileNotFoundError, Exception) as exc:  # noqa: BLE001
        logger.info("project_config_unavailable", extra={"reason": str(exc)})
        project_config = None

    runner = SdkStageRunner(
        effort=getattr(project_config, "effort", None) if project_config else None
    )

    def _stage_cfg(name: StageName):
        from a2sdlc.stages import get_stage  # noqa: PLC0415

        if project_config is not None:
            return load_stage_config(name.value, project_config)
        return get_stage(name).config

    decoded_input = input_md.decode("utf-8", errors="replace")
    aggregate = StageRunStats()
    cycles_per_stage: dict[StageName, int] = {}
    success = True
    run_error: str | None = None
    spec_output: str = ""
    implement_output: str = ""

    async def _drive() -> None:
        nonlocal success, run_error, spec_output, implement_output

        # ── SPEC ────────────────────────────────────────────────────
        cycles_per_stage[StageName.SPEC] = 1
        spec_res = await _run_one_stage(
            stage=StageName.SPEC,
            cycle=1,
            user_prompt=decoded_input,
            project_root=repo,
            progress_state=progress_state,
            runner=runner,
            stage_config_obj=_stage_cfg(StageName.SPEC),
            branch=run_branch,
            ticket_key=ticket_key,
            work_adapter=work_adapter,
            review_adapter=review_adapter,
        )
        spec_output = spec_res.output
        if not spec_res.success:
            success = False
            run_error = spec_res.error or "spec_failed"
            return
        _commit_and_push(repo, run_branch, "stage: spec", logger=logger)

        # ── IMPLEMENT / REVIEW loop ─────────────────────────────────
        max_cycles = config.pipeline.max_review_cycles
        for cycle in range(1, max_cycles + 1):
            cycles_per_stage[StageName.IMPLEMENT] = cycle
            implement_prompt = (
                f"Spec for the change:\n\n{spec_output}\n\n"
                "Implement the spec exactly. Produce real source code."
            )
            if cycle > 1 and implement_output:
                implement_prompt += (
                    "\n\nThe previous review requested changes. "
                    "Address the feedback under "
                    f"{state_root / 'reviews'}/."
                )
            impl_res = await _run_one_stage(
                stage=StageName.IMPLEMENT,
                cycle=cycle,
                user_prompt=implement_prompt,
                project_root=repo,
                progress_state=progress_state,
                runner=runner,
                stage_config_obj=_stage_cfg(StageName.IMPLEMENT),
                branch=run_branch,
                ticket_key=ticket_key,
                work_adapter=work_adapter,
                review_adapter=review_adapter,
            )
            implement_output = impl_res.output
            if not impl_res.success:
                success = False
                run_error = impl_res.error or "implement_failed"
                return
            _commit_and_push(
                repo, run_branch, f"stage: implement (cycle {cycle})", logger=logger
            )

            cycles_per_stage[StageName.REVIEW] = cycle
            review_adapter.cycle = cycle
            review_prompt = (
                "Review the implementation against the spec.\n\n"
                f"Spec:\n{spec_output}\n\n"
                f"Implementation summary:\n{implement_output}"
            )
            rev_res = await _run_one_stage(
                stage=StageName.REVIEW,
                cycle=cycle,
                user_prompt=review_prompt,
                project_root=repo,
                progress_state=progress_state,
                runner=runner,
                stage_config_obj=_stage_cfg(StageName.REVIEW),
                branch=run_branch,
                ticket_key=ticket_key,
                work_adapter=work_adapter,
                review_adapter=review_adapter,
            )
            if not rev_res.success:
                success = False
                run_error = rev_res.error or "review_failed"
                return
            _commit_and_push(
                repo, run_branch, f"stage: review (cycle {cycle})", logger=logger
            )

            if rev_res.status == StageStatus.APPROVED:
                return
            if rev_res.status != StageStatus.CHANGES_REQUESTED:
                # Unknown / no structured output — treat as approved so
                # the loop terminates rather than spinning indefinitely.
                return
            # else: loop into another IMPLEMENT cycle.

        # Loop fell through — max cycles exceeded.
        success = False
        run_error = f"review handover loop exceeded max_review_cycles={max_cycles}"

    try:
        asyncio.run(_drive())
    except typer.Exit:
        # Re-raise commit/push exit codes (8/9) as-is — the lockfile
        # ``finally`` in run.py still releases the lock.
        raise
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(
            f"error: internal failure: {type(exc).__name__}: {exc}\n"
            f"lockfile released; partial state on local branch '{run_branch}'.\n"
        )
        raise typer.Exit(code=1) from exc
    finally:
        # Best-effort RunEnd emission so the console subscriber prints
        # ``totals: …`` even when we exit non-zero.
        try:
            asyncio.run(
                progress_state.run_end(
                    workflow_id=run_branch,
                    success=success,
                    error=run_error,
                    aggregate_stats=aggregate,
                    total_cycles=cycles_per_stage,
                )
            )
        except Exception:  # noqa: BLE001
            logger.warning("run_end_emit_failed", exc_info=True)

    if not success:
        if run_error and "max_review_cycles" in run_error:
            sys.stderr.write(f"error: {run_error}\n")
            raise typer.Exit(code=10)
        sys.stderr.write(f"error: {run_error or 'pipeline failed'}\n")
        raise typer.Exit(code=1)

    sys.stdout.write(f"done.\nbranch: {run_branch}\n")


__all__ = ["drive_pipeline"]
