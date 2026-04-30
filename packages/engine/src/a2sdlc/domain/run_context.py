"""``RunContext`` — per-dispatch run context.

Lives in ``domain/`` because handlers, interpreter, ingress, and
gating all need to share a single ambient state object. Domain purity
is preserved by typing adapter handles and lifecycle/evaluation
references as ``Any`` — matching the precedent set by ``RunIntent``
and ``RunResult.progress``. Pipeline-layer consumers (``dispatch.py``)
narrow the types at the boundary where needed.

The shape is deliberately transitional: ``pr_lifecycle``/``comment``/
``pr_number``/``stage_config``/``run`` stay populated per-run for
handler compat (unchanged from the P2/P3 fat-context pattern). A later
phase tightens these fields once handler signatures move to
``execute(ctx, intent)``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from a2sdlc.domain.run_intent import RunIntent


@dataclass
class RunContext:
    """Per-dispatch run context.

    Ambient state object carried through the full run lifecycle. The
    non-``Any`` fields below are the engine's own domain types; every
    ``Any``-typed field is an adapter handle or an observability/
    evaluation object whose real type lives outside ``domain/``.
    """

    # Adapter handles. Runtime types: adapters.work.WorkAdapter,
    # adapters.git.GitAdapter, adapters.review.ReviewAdapter,
    # adapters.runner.StageRunner. Opaque here to keep domain/ pure.
    work: Any
    git: Any
    review: Any
    runner: Any
    # Observability / config. Runtime types: domain.progress.ProgressState,
    # config.ProjectConfig, logging.Logger.
    progress_state: Any
    config: Any
    project_root: Path
    logger: Any
    run_id: str | None = None
    # Factory: (CommentManager) -> Subscriber. Kept ``Any`` for purity.
    make_comment_subscriber: Callable[[Any], Any] | None = None
    # Optional telemetry. Runtime type: evaluation.telemetry.Telemetry.
    telemetry: Any = None
    # ── per-run orchestration state (populated by dispatch before handler.execute) ──
    intent: RunIntent | None = None
    pr_lifecycle: Any = None
    comment: Any = None
    pr_number: int | None = None
    stage_config: Any = None
    run: Any = None
    # Pre-built ``pipeline.stage_executor.StageExecutor`` bound to
    # ``runner`` — populated by dispatch before handler.execute. Stage
    # handlers call ``ctx.stage_executor.run(...)`` so they don't need
    # to import from ``pipeline/`` directly.
    stage_executor: Any = None


@dataclass
class PipelineRun:
    """Persisted identity for a single workflow run (v1 schema).

    Carries the engine-internal addressing (``workflow_id`` = run-branch
    name) and the human/tracker-facing label (``ticket_key``) plus the
    base-branch coordinates captured at workflow start. Per the workflow-
    primitives design, ``state.json`` must only be loaded when its branch
    matches the current branch — that invariant is enforced by callers.

    Field defaults exist so partially-populated fixtures and migrations
    can construct instances incrementally; production code paths should
    set every field explicitly.
    """

    workflow_id: str = ""
    ticket_key: str | None = None
    base: str = ""
    base_sha: str = ""
    ecosystem: str = "local"
    schema_version: int = 1


__all__ = ["PipelineRun", "RunContext"]
