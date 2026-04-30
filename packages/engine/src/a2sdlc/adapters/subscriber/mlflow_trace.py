"""MlflowTraceSubscriber — emits MLflow spans for each pipeline stage and tool call.

Writes into the currently-active MLflow run opened by ``MlflowTelemetry``
(see ``evaluation/telemetry.py``) before dispatch runs. One root span per stage, one child span per tool invocation.
The stage span carries cumulative metrics as attributes (overwritten on every
``Metrics`` event) and final metrics on close.

Uses ``mlflow.start_span_no_context`` so parent-child relationships are
managed explicitly — the MLflow context-manager API is a poor fit for an
event-driven bus where ``StageStart`` and ``StageEnd`` arrive on different
stack frames.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import mlflow

from a2sdlc.domain.progress import (
    Metrics,
    Milestone,
    ProgressEvent,
    StageEnd,
    StageStart,
    ToolEntry,
)

if TYPE_CHECKING:
    from mlflow.entities import LiveSpan


class MlflowTraceSubscriber:
    """Emits MLflow spans for each pipeline stage and tool call."""

    def __init__(self) -> None:
        self._stage_span: LiveSpan | None = None
        self._tool_span: LiveSpan | None = None

    def start_run(
        self,
        *,
        workflow_id: str,
        ticket_key: str | None,
        base: str,
        base_sha: str,
        ecosystem: str,
        input_hash: str,
        engine_version: str,
    ) -> object:
        """Open the MLflow parent run for a workflow with identity tags.

        Spec §MLflow correlation: ``run_name`` is the workflow_id (which is
        also the run-branch name). Tags carry the identity fields needed to
        correlate runs across replays / re-records / parallel A/B tests.
        ``ticket_key`` is omitted when the run is autonomous (no ticket).
        """
        tags: dict[str, str] = {
            "base": base,
            "base_sha": base_sha,
            "ecosystem": ecosystem,
            "input_hash": input_hash,
            "engine_version": engine_version,
        }
        if ticket_key:
            tags["ticket_key"] = ticket_key
        return mlflow.start_run(run_name=workflow_id, tags=tags)

    async def handle(self, event: ProgressEvent) -> None:
        if isinstance(event, StageStart):
            self._stage_span = mlflow.start_span_no_context(
                name=f"stage:{event.stage.value}",
                attributes={"session_id": event.session_id},
            )
        elif isinstance(event, ToolEntry):
            self._close_tool_span()
            if self._stage_span is None:
                return
            tool_span = mlflow.start_span_no_context(
                name=f"tool:{event.name}",
                parent_span=self._stage_span,
            )
            # start_span_no_context's `attributes` kwarg is typed dict[str, str].
            # Use set_attributes for the numeric elapsed value.
            tool_span.set_attributes(
                {"target": event.target, "elapsed": event.timestamp}
            )
            self._tool_span = tool_span
        elif isinstance(event, Metrics):
            if self._stage_span is not None:
                self._stage_span.set_attributes(
                    {
                        "tokens_in": event.input_tokens,
                        "tokens_out": event.output_tokens,
                        "cost_usd": event.total_cost_usd,
                        "num_turns": event.num_turns,
                    }
                )
        elif isinstance(event, Milestone):
            if self._stage_span is not None:
                self._stage_span.set_attribute(
                    f"milestone:{event.timestamp}", event.label
                )
        elif isinstance(event, StageEnd):
            self._close_tool_span()
            if self._stage_span is not None:
                self._stage_span.set_attributes(
                    {
                        "success": event.success,
                        "error": event.error or "",
                        "final_cost_usd": event.final_metrics.total_cost_usd,
                        "final_tokens_in": event.final_metrics.input_tokens,
                        "final_tokens_out": event.final_metrics.output_tokens,
                        "final_num_turns": event.final_metrics.num_turns,
                    }
                )
                self._stage_span.end()
                self._stage_span = None

    def _close_tool_span(self) -> None:
        if self._tool_span is not None:
            self._tool_span.end()
            self._tool_span = None
