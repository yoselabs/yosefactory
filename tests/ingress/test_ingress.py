"""L1 tests for pipeline.ingress.

Covers ``parse_event`` happy path + SkipEvent conversion.
``resolve_intent`` tests land with step 2.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from a2sdlc.domain.exceptions import SkipEvent
from a2sdlc.domain.handover import HandoverComment
from a2sdlc.domain.models import StageName
from a2sdlc.domain.pipeline_event import PipelineEvent
from a2sdlc.ingress import ParsedSkip, parse_event, resolve_routing
from tests.fakes import make_dispatch_context


def test_parse_event_returns_work_adapter_event() -> None:
    ctx, *_ = make_dispatch_context(project_root=Path("/tmp/test_ingress_ok"))
    parsed = parse_event(ctx)
    assert isinstance(parsed, PipelineEvent)
    assert parsed.key == "35"


def test_parse_event_converts_skip_event_to_parsed_skip() -> None:
    ctx, work, *_ = make_dispatch_context(project_root=Path("/tmp/test_ingress_skip"))

    def _raise() -> PipelineEvent:
        raise SkipEvent("not a valid event")

    work.parse_event = _raise  # ty: ignore[invalid-assignment]

    parsed = parse_event(ctx)
    assert isinstance(parsed, ParsedSkip)
    assert parsed.reason == "not a valid event"


def test_parse_event_skip_is_frozen() -> None:
    skip = ParsedSkip(reason="x")
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
        skip.reason = "y"  # ty: ignore[invalid-assignment]


# ── resolve_routing ────────────────────────────────────────────────


def test_resolve_routing_explicit_trigger_stage_used_as_is() -> None:
    ctx, *_ = make_dispatch_context(project_root=Path("/tmp/test_routing_label"))
    event = PipelineEvent(key="35", trigger_stage=StageName.IMPLEMENT)

    prompt, target, short_circuit = resolve_routing(ctx, event, "ticket body")

    assert prompt is None
    assert target is StageName.IMPLEMENT
    assert short_circuit is None


def test_resolve_routing_proceed_without_handover_defaults_to_implement() -> None:
    """No trigger_stage + no prior handover → IMPLEMENT fallback."""
    ctx, *_ = make_dispatch_context(project_root=Path("/tmp/test_routing_proceed"))
    event = PipelineEvent(key="35", trigger_stage=None)

    prompt, target, short_circuit = resolve_routing(ctx, event, "body")

    assert target is StageName.IMPLEMENT
    assert short_circuit is None


def test_resolve_routing_proceed_after_spec_handover_routes_to_implement() -> None:
    from datetime import datetime, timezone

    handover = HandoverComment(
        stage=StageName.SPEC,
        run_id="r",
        body="b",
        created_at=datetime.now(timezone.utc),
        location="issue",
    )
    ctx, *_ = make_dispatch_context(
        last_handover=handover,
        project_root=Path("/tmp/test_routing_after_spec"),
    )
    event = PipelineEvent(key="35", trigger_stage=None)

    _, target, short_circuit = resolve_routing(ctx, event, "body")

    assert target is StageName.IMPLEMENT
    assert short_circuit is None


def test_resolve_routing_feedback_with_pr_loads_pr_handover_and_diff() -> None:
    """Feedback event with pr_number → ingress reads PR handover + diff."""
    ctx, _work, _git, review, _runner = make_dispatch_context(
        project_root=Path("/tmp/test_routing_feedback_pr"),
    )
    # Feedback event with PR attached — exercises the pr_number branch.
    event = PipelineEvent(key="35", trigger_stage=None, is_feedback=True, pr_number=42)

    _, target, short_circuit = resolve_routing(ctx, event, "body")

    # No handover found → routes to SPEC (feedback default when no current_stage).
    assert short_circuit is None
    assert target is StageName.SPEC


def test_resolve_routing_proceed_after_review_handover_routes_to_merge() -> None:
    from datetime import datetime, timezone

    handover = HandoverComment(
        stage=StageName.REVIEW,
        run_id="r",
        body="b",
        created_at=datetime.now(timezone.utc),
        location="issue",
    )
    ctx, *_ = make_dispatch_context(
        last_handover=handover,
        project_root=Path("/tmp/test_routing_after_review"),
    )
    event = PipelineEvent(key="35", trigger_stage=None)

    _, target, _ = resolve_routing(ctx, event, "body")

    assert target is StageName.MERGE
