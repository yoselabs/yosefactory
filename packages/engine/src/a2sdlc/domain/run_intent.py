"""``RunIntent`` — what the pipeline intends to do for a single run.

Pure data type. Produced by ``pipeline.ingress.resolve_intent`` once
event parsing and routing have settled. Consumed by stage handlers via
``ctx.intent``.

``state_mgr`` is typed as ``Any`` to keep ``domain`` free of any
runtime dependency on ``lifecycle`` — matching the precedent set by
``run_result.RunResult.progress``. Consumers that need the real
``StateManager`` interface cast at the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from a2sdlc.domain.models import GateConfig, StageName, TicketState
from a2sdlc.domain.pipeline_event import PipelineEvent


@dataclass
class RunIntent:
    """Resolved inputs for a single stage run."""

    event: PipelineEvent
    target_stage: StageName
    clean_body: str
    user_prompt_override: str | None
    gates: GateConfig
    self_answer: bool
    # Runtime type: lifecycle.state.StateManager. Opaque here to keep
    # domain/ pure — consumers cast as needed.
    state_mgr: Any
    state: TicketState | None
    base: str
    branch: str


__all__ = ["RunIntent"]
