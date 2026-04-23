"""L1 tests for pipeline.ingress.

Covers ``parse_event`` happy path + SkipEvent conversion.
``resolve_intent`` tests land with step 2.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from a2sdlc.domain.exceptions import SkipEvent
from a2sdlc.domain.pipeline_event import PipelineEvent
from a2sdlc.pipeline.ingress import ParsedSkip, parse_event
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
