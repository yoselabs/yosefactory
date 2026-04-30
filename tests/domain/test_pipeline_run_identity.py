"""Identity & schema fields on the persisted PipelineRun state."""

from __future__ import annotations

from a2sdlc.domain.run_context import PipelineRun


def test_pipeline_run_carries_v1_identity_fields() -> None:
    run = PipelineRun(
        workflow_id="a2sdlc/auto/req-x/20260430-142208-a3f019",
        ticket_key="ABC-123",
        base="req/x",
        base_sha="0" * 40,
        ecosystem="local",
        schema_version=1,
    )
    assert run.workflow_id == "a2sdlc/auto/req-x/20260430-142208-a3f019"
    assert run.ticket_key == "ABC-123"
    assert run.base == "req/x"
    assert run.base_sha == "0" * 40
    assert run.ecosystem == "local"
    assert run.schema_version == 1


def test_ticket_key_optional() -> None:
    run = PipelineRun(
        workflow_id="a2sdlc/auto/req-x/20260430-142208-a3f019",
        ticket_key=None,
        base="req/x",
        base_sha="0" * 40,
        ecosystem="local",
        schema_version=1,
    )
    assert run.ticket_key is None
