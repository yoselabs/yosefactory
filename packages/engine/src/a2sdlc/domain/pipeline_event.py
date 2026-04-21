"""PipelineEvent — normalized work-adapter event.

Pure dataclass; crosses the pipeline↔adapter boundary. Consumed by both
``pipeline/dispatch.py`` and every ``WorkAdapter.parse_event()`` impl.
Lives in ``domain/`` because it has no I/O dependencies and both layers
need it.
"""

from __future__ import annotations

from dataclasses import dataclass

from a2sdlc.domain.models import StageName


@dataclass
class PipelineEvent:
    """Normalized pipeline event from a work adapter.

    trigger_stage: what the event literally says (label value, or None for feedback/proceed).
    is_feedback: True for comment/review events, False for label events.
    The engine resolves the actual target stage via the routing table.
    """

    key: str
    trigger_stage: StageName | None = None
    is_feedback: bool = False
    pr_number: int | None = None
    # Human (or tracker-native) ticket-closed signal. Engine handles this
    # without running any AI stage: strip transient stage:* labels, stamp
    # stage:done, no branch work.
    is_closed: bool = False


__all__ = ["PipelineEvent"]
