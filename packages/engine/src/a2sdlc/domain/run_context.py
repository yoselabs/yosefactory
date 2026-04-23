"""``RunContext`` — per-dispatch run context.

Lives in ``domain/`` because handlers, interpreter, ingress, and
gating all need to share a single ambient state object. Domain purity
is preserved by typing adapter handles and lifecycle/evaluation
references as ``Any`` — matching the precedent set by ``RunIntent``
and ``RunResult.progress``. Pipeline-layer consumers (``dispatch.py``)
narrow the types at the boundary where needed.

The shape is deliberately transitional: ``pre``/``pr_lifecycle``/
``comment``/``pr_number``/``stage_config``/``run`` stay populated per-
run for handler compat (unchanged from the P2/P3 fat-context pattern).
``intent`` is introduced alongside ``pre`` so readers that don't need
the legacy ``PreflightOutcome`` name can import the renamed type.
A later phase tightens these fields once handler signatures move to
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
    pre: RunIntent | None = None
    intent: RunIntent | None = None
    pr_lifecycle: Any = None
    comment: Any = None
    pr_number: int | None = None
    stage_config: Any = None
    run: Any = None


__all__ = ["RunContext"]
