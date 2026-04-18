# MLflow Trace Subscriber Handover — 2026-04-18

## Status

Branch `feat/local-runner` is **merge-ready as-is** (47 commits ahead of main, 515 tests pass, lint clean, smoke-validated end-to-end). The progress-subscribers refactor and the local-runner work are both complete. The handover at `docs/superpowers/handovers/2026-04-18-local-runner-handover.md` covers that history.

This handover is for **one remaining piece of work** that surfaced during the smoke validation: **MLflow traces are missing from each run's "Traces" tab.** Today MLflow gets only final per-stage metrics — no span-tree of the agent's tool calls.

The work to add traces is small and well-scoped, but it deserves its own session. **Do this BEFORE merging the branch** — it's a natural extension of the subscriber pattern and slots in cleanly.

## What's already true

- `ProgressState` is a pub/sub bus emitting `StageStart`, `ToolEntry`, `GroupOpen`, `GroupClose`, `Metrics`, `Milestone`, `StageEnd` events.
- Three subscribers exist: `ConsoleSubscriber` (rich.Live), `GhActionsLogSubscriber` (`::group::` markers), `GhCommentSubscriber` (throttled comment edits).
- MLflow integration: `MlflowSink` opens a parent run per session and a child run per stage. Final cost/tokens/turns/duration are logged as metrics on the child. **No `mlflow.start_span` calls anywhere.**
- The session/stage MLflow run is opened in `cli_local.py:213-220` *before* `dispatch()` is called — so any subscriber registered on `progress_state` will have an active MLflow run to write into via `mlflow.start_span()`.

## What's NOT going to work (already verified)

`mlflow.anthropic.autolog()` is a dead end. `claude_agent_sdk` (v0.1.56) shells out to a bundled `claude` CLI subprocess (`claude_agent_sdk._bundled.claude`) — it does NOT use the `anthropic` Python SDK. MLflow's autolog hooks the Anthropic Python SDK's HTTP path, which we never execute. Even installing the `anthropic` package as a dep wouldn't help. **Do not waste time trying autolog variants.**

## What to build: `MlflowTraceSubscriber`

Add a fourth subscriber that consumes `ProgressEvent`s and emits MLflow spans.

### Mapping

| Event | MLflow action |
|---|---|
| `StageStart` | open a top-level span `stage:<name>` with attrs `{session_id, model, max_turns}`; push onto stack |
| `ToolEntry` | close current tool span (if any); open child span `tool:<name>` with attrs `{target, elapsed}`; push onto stack |
| `Milestone` | annotate the active stage span via `span.set_attribute("milestone:<n>", label)` (or `set_inputs` keyed by timestamp — see open question below) |
| `GroupOpen` / `GroupClose` | ignore (these were a vestigial concept; subscriber doesn't need them) |
| `Metrics` | `span.set_attributes({tokens_in, tokens_out, cost_usd, num_turns})` on the active stage span — overwrites previous attrs (cumulative semantics) |
| `StageEnd` | close any open tool span; close the stage span. Set `success` / `error` as attributes; set `final_metrics` as attributes/outputs. |

### Skeleton

```python
# src/a2sdlc/adapters/mlflow_trace_subscriber.py
from __future__ import annotations

import mlflow
from mlflow.entities import LiveSpan

from a2sdlc.evaluation.progress import (
    Metrics, Milestone, ProgressEvent, StageEnd, StageStart, ToolEntry,
)


class MlflowTraceSubscriber:
    """Emits MLflow spans for each pipeline stage and tool call.

    Spans are written into the currently-active MLflow run (opened by
    MlflowSink before dispatch runs). One root span per stage, one child
    span per tool invocation. Stage span attributes carry the latest
    cumulative metrics and the final_metrics on close.
    """

    def __init__(self) -> None:
        self._stage_span: LiveSpan | None = None
        self._stage_cm = None  # context manager handle
        self._tool_span: LiveSpan | None = None
        self._tool_cm = None

    async def handle(self, event: ProgressEvent) -> None:
        if isinstance(event, StageStart):
            self._stage_cm = mlflow.start_span(
                name=f"stage:{event.stage.value}",
                attributes={"session_id": event.session_id},
            )
            self._stage_span = self._stage_cm.__enter__()
        elif isinstance(event, ToolEntry):
            self._close_tool_span()
            self._tool_cm = mlflow.start_span(
                name=f"tool:{event.name}",
                attributes={"target": event.target, "elapsed": event.timestamp},
            )
            self._tool_span = self._tool_cm.__enter__()
        elif isinstance(event, Metrics):
            if self._stage_span is not None:
                self._stage_span.set_attributes({
                    "tokens_in": event.input_tokens,
                    "tokens_out": event.output_tokens,
                    "cost_usd": event.total_cost_usd,
                    "num_turns": event.num_turns,
                })
        elif isinstance(event, Milestone):
            if self._stage_span is not None:
                # Open question: use set_attribute or set_inputs? See below.
                self._stage_span.set_attribute(f"milestone:{event.timestamp}", event.label)
        elif isinstance(event, StageEnd):
            self._close_tool_span()
            if self._stage_span is not None:
                self._stage_span.set_attributes({
                    "success": event.success,
                    "error": event.error or "",
                    "final_cost_usd": event.final_metrics.total_cost_usd,
                    "final_tokens_in": event.final_metrics.input_tokens,
                    "final_tokens_out": event.final_metrics.output_tokens,
                    "final_num_turns": event.final_metrics.num_turns,
                })
                self._stage_cm.__exit__(None, None, None)
                self._stage_span = None
                self._stage_cm = None

    def _close_tool_span(self) -> None:
        if self._tool_cm is not None:
            self._tool_cm.__exit__(None, None, None)
            self._tool_cm = None
            self._tool_span = None
```

### Wiring

In `cli_local.py`, register alongside the other subscribers when `sink is not None`:

```python
if sink is not None:
    from a2sdlc.adapters.mlflow_trace_subscriber import MlflowTraceSubscriber
    progress_state.subscribe(MlflowTraceSubscriber())
```

Same edit in `cli.py` for GH dispatch.

**Important ordering note:** the MLflow run must be active when `StageStart` fires. Today the run is opened by `sink.session()` / `sess.stage_run()` context managers in `cli_local.py:213-220`, BEFORE `dispatch()` is called. Inside dispatch, `progress_state.stage_start()` fires (after `comment.start()`) — so the run is active by then. ✓

The MLflow autolog is `mlflow.start_span()` aware of the active run — no explicit run_id needed.

## Open questions for the next session

1. **Span lifecycle vs. context manager protocol.** MLflow's `start_span` is documented as a context manager. Calling `__enter__` / `__exit__` manually outside a `with` block is the right pattern for our event-driven case, but verify it actually works — the LiveSpan might get garbage-collected if we drop the context manager reference. The skeleton holds both `_stage_cm` and `_stage_span` for safety.

2. **Milestone attribute key collision.** `set_attribute(f"milestone:{event.timestamp}", event.label)` uses the timestamp as part of the key. If two milestones fire at the exact same float-second, they collide. Probably fine in practice; alternatively use `set_inputs([Milestone events])` cumulative pattern.

3. **Async safety of `mlflow.start_span`.** Subscribers are awaited sequentially in the bus, but `mlflow.start_span` is sync. Verify it doesn't deadlock or misbehave under asyncio. The MLflow tracing client uses background workers — should be fine.

4. **Failure containment.** If `mlflow.start_span` raises (e.g., MLflow backend unreachable mid-stage), `ProgressState._emit` catches the exception, adds the subscriber to `_failed`, and skips it for the rest of the stage. The other subscribers and the stage itself continue. ✓ — already handled by the bus.

5. **GHA CI.** The current `cli.py` doesn't construct an `MlflowSink` — only `cli_local.py` does. Decide whether to enable MLflow + this subscriber on the GH-dispatch path too, or leave it local-only. Probably out of scope for this ticket.

## Test plan

- Unit: `tests/adapters/test_mlflow_trace_subscriber.py`. Mock `mlflow.start_span` with a fake context manager that records calls. Assert correct nesting (StageStart opens span; ToolEntry opens child; second ToolEntry closes first child and opens a new one; StageEnd closes everything).
- Integration: extend `tests/pipeline/test_dispatch_progress.py` — register `MlflowTraceSubscriber`, run dispatch, assert mock recorded the expected sequence of `start_span` calls.
- Manual: run the smoke (`a2sdlc-smoke` workspace, fresh session `smoke5`) and look at http://127.0.0.1:5555 — the Traces tab on `smoke5:spec` and `smoke5:implement` should show a span tree.

## Acceptance

- New file `src/a2sdlc/adapters/mlflow_trace_subscriber.py` with the class above.
- New tests for the subscriber.
- `cli_local.py` (and optionally `cli.py`) registers the subscriber when MLflow tracking is enabled.
- `make check` green.
- Smoke on `a2sdlc-smoke` shows non-empty Traces tab in MLflow UI.
- Update `pyproject.toml` `ignore_imports` if needed (the new subscriber imports from `evaluation.progress`, same pattern as existing subscribers).

## Merge order

1. Land `MlflowTraceSubscriber` on `feat/local-runner`.
2. Final smoke (SPEC + IMPLEMENT) confirming traces appear.
3. Merge `feat/local-runner` → `main`.

No need to split into a separate branch — the subscriber is a small additive piece that completes the observability story this branch already builds.
