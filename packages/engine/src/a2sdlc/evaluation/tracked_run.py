"""Orchestrate a dispatch run under an MLflow sink + quality-gate.

Pulls the tracking orchestration out of the CLI. Takes a zero-arg async
``dispatch_fn`` (caller has already bound the ``DispatchContext``) so this
module stays off the pipeline → evaluation dependency path.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any

from a2sdlc.domain.models import StageName
from a2sdlc.domain.run_result import DispatchResult
from a2sdlc.evaluation.quality_gate import QualityResult, run_quality_gate

if TYPE_CHECKING:
    from a2sdlc.evaluation.mlflow_sink import MlflowSink


DispatchFn = Callable[[], Coroutine[Any, Any, DispatchResult]]


def run_tracked(
    *,
    dispatch_fn: DispatchFn,
    sink: "MlflowSink | None",
    stage: StageName,
    session_id: str,
    project_root: Path,
    quality_command: str,
    sha_before: str,
    dirty: bool,
) -> tuple[DispatchResult, QualityResult | None]:
    """Run ``dispatch_fn``; log metrics/artifacts if ``sink`` is active.

    On IMPLEMENT stages that succeed, also runs the quality gate and logs
    its artifact to the active MLflow child run.
    """
    if sink is None:
        result = asyncio.run(dispatch_fn())
        quality = _maybe_run_quality_gate(stage, result, project_root, quality_command)
        return result, quality

    import mlflow as _mlflow  # noqa: PLC0415

    with (
        sink.session(session_id) as sess,
        sess.stage_run(stage=stage.value) as child,
    ):
        child.log_tag("git_sha_before", sha_before)
        child.log_tag("dirty_tree_before", "true" if dirty else "false")
        child.log_tag("session_id", session_id)

        result = asyncio.run(dispatch_fn())

        stats = result.stats
        if stats is not None:
            child.log_metric("tokens_in", stats.tokens_in)
            child.log_metric("tokens_out", stats.tokens_out)
            child.log_metric("cost_usd", stats.cost_usd)
            child.log_metric("turns", stats.num_turns)
            child.log_metric("duration_ms", stats.duration_ms)

        _mlflow.log_dict(
            _stage_output_artifact(stage, session_id, result),
            f"{stage.value}-output.json",
        )

        quality = _maybe_run_quality_gate(stage, result, project_root, quality_command)
        if quality is not None:
            child.log_metric("quality_passed", 1 if quality.passed else 0)
            artifact_path = project_root / ".a2sdlc" / "quality.log"
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text(quality.output)
            _mlflow.log_artifact(str(artifact_path))

    return result, quality


def _maybe_run_quality_gate(
    stage: StageName,
    result: DispatchResult,
    project_root: Path,
    quality_command: str,
) -> QualityResult | None:
    """Run the quality gate iff this was a successful IMPLEMENT stage."""
    if stage != StageName.IMPLEMENT or result.blocked or result.error is not None:
        return None
    return run_quality_gate(project_root=project_root, command=quality_command)


def _stage_output_artifact(
    stage: StageName, session_id: str, result: DispatchResult
) -> dict[str, object]:
    """Build the JSON payload logged as the stage output artifact."""
    stats = result.stats
    stats_payload: dict[str, float | int] = {}
    if stats is not None:
        stats_payload = {
            "tokens_in": stats.tokens_in,
            "tokens_out": stats.tokens_out,
            "cost_usd": stats.cost_usd,
            "num_turns": stats.num_turns,
            "duration_ms": stats.duration_ms,
        }
    return {
        "stage": stage.value,
        "session_id": session_id,
        "success": not result.blocked and result.error is None,
        "blocked": result.blocked,
        "error": result.error,
        "status": result.status.value if result.status else None,
        "next_stage": result.next_stage.value if result.next_stage else None,
        "output": result.output,
        "stats": stats_payload,
    }
