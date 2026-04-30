"""ConsoleSubscriber — three-rhythm plain-text renderer (default for CLI/local
mode) plus the legacy rich.Live status-pane mode (kept for callers that pass a
``ProgressState``).

Spec §Console output cadence. Three rhythms per stage:

1. ``[STAGE]    starting (cycle N)`` on ``StageStart``.
2. Mid-stage event log lines (Milestone, ToolEntry, GroupOpen, GroupClose) —
   one line each, prefixed with the stage tag.
3. Stage end: optional output block (between
   ``===== a2sdlc:stage-output BEGIN/END =====`` fences when
   ``StageEnd.artifact_path`` is a real file) followed by a stats line
   ``<duration> · <turns> turns · <tokens-in> in / <tokens-out> out · <cost>``.

Plus a final ``totals:`` (or ``totals (failed):`` + error) line on ``RunEnd``.
"""

from __future__ import annotations

from collections import deque
from typing import TextIO

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from a2sdlc.domain.models import StageName
from a2sdlc.domain.progress import (
    GroupClose,
    GroupOpen,
    Metrics,
    Milestone,
    ProgressEvent,
    ProgressState,
    RunEnd,
    StageEnd,
    StageStart,
    ToolEntry,
)
from a2sdlc.domain.progress_format import _format_duration, _format_tokens_precise
from a2sdlc.domain.stats import StageRunStats


_FENCE_BEGIN = "===== a2sdlc:stage-output BEGIN ====="
_FENCE_END = "===== a2sdlc:stage-output END ====="

# Total visual width of the bracketed stage tag including padding spaces.
# `[IMPLEMENT]` is 11 chars + 1 trailing space = 12. `[SPEC]` (6 chars) needs
# 6 trailing spaces; `[REVIEW]` (8 chars) needs 4. Columns align across stages.
_TAG_WIDTH = 12


def _stage_tag(stage: StageName) -> str:
    """Fixed-width tag, e.g. '[SPEC]      ', '[IMPLEMENT] ', '[REVIEW]    '."""
    raw = f"[{stage.value.upper()}]"
    pad = max(1, _TAG_WIDTH - len(raw))
    return raw + (" " * pad)


def _format_cost(usd: float) -> str:
    return f"${usd:.2f}"


def _stats_from_metrics(m: Metrics | None) -> str:
    if m is None:
        return "- · - turns · - in / - out · -"
    return (
        f"{_format_duration(m.elapsed)} · "
        f"{m.num_turns} turns · "
        f"{_format_tokens_precise(m.input_tokens)} in / "
        f"{_format_tokens_precise(m.output_tokens)} out · "
        f"{_format_cost(m.total_cost_usd)}"
    )


def _stats_from_run_stats(s: StageRunStats) -> str:
    return (
        f"{_format_duration(s.duration_ms / 1000)} · "
        f"{s.num_turns} turns · "
        f"{_format_tokens_precise(s.tokens_in)} in / "
        f"{_format_tokens_precise(s.tokens_out)} out · "
        f"{_format_cost(s.cost_usd)}"
    )


class ConsoleSubscriber:
    """Console renderer.

    Two modes, selected by constructor args:

    * **Plain-text mode** (``stream=...``): three-rhythm renderer for
      CLI/local mode. Tests drive this with ``io.StringIO()``.
    * **Legacy rich.Live mode** (``state=ProgressState``): in-place
      scrolling pane plus status bar. Used by ``observability.wire``
      and ``composition`` for the existing ticket-board pipeline.

    If both are passed, plain-text mode wins.
    """

    _MAX_EVENTS = 20

    def __init__(
        self,
        state: ProgressState | None = None,
        *,
        stream: TextIO | None = None,
    ) -> None:
        self._stream: TextIO | None = stream
        self._state = state
        # Plain-text bookkeeping
        self._cycle_counts: dict[StageName, int] = {}
        self._current_stage: StageName | None = None
        # Legacy rich.Live bookkeeping (only used when state is not None and
        # stream is None)
        self.recent_events: deque[str] = deque(maxlen=self._MAX_EVENTS)
        self._stage_name: str = "-"
        self._session_id: str = ""
        self._live: Live | None = None
        self._console = Console()

    # ── Plain-text mode helpers ────────────────────────────────────

    def _is_plain(self) -> bool:
        return self._stream is not None

    def _write(self, line: str) -> None:
        assert self._stream is not None
        self._stream.write(line + "\n")

    def _flush(self) -> None:
        if self._stream is not None and hasattr(self._stream, "flush"):
            try:
                self._stream.flush()
            except Exception:  # noqa: BLE001
                pass

    def _tag_for_event(self, event: ProgressEvent) -> str:
        """Best-effort stage tag for events that lack a stage field."""
        stage: StageName | None = getattr(event, "stage", None)
        if stage is None:
            stage = self._current_stage
        if stage is None:
            return " " * _TAG_WIDTH
        return _stage_tag(stage)

    async def _handle_plain(self, event: ProgressEvent) -> None:
        if isinstance(event, StageStart):
            self._current_stage = event.stage
            count = self._cycle_counts.get(event.stage, 0) + 1
            self._cycle_counts[event.stage] = count
            self._write(f"{_stage_tag(event.stage)}starting (cycle {count})")
        elif isinstance(event, Milestone):
            self._write(f"{self._tag_for_event(event)}{event.label}")
        elif isinstance(event, ToolEntry):
            target = f" {event.target}" if event.target else ""
            self._write(f"{self._tag_for_event(event)}tool: {event.name}{target}")
        elif isinstance(event, GroupOpen):
            self._write(f"{self._tag_for_event(event)}▶ {event.title}")
        elif isinstance(event, GroupClose):
            self._write(f"{self._tag_for_event(event)}◀ end")
        elif isinstance(event, Metrics):
            # No-op: per-tick metrics are noisy in plain mode; final stats
            # come out of StageEnd.
            pass
        elif isinstance(event, StageEnd):
            artifact = event.artifact_path
            if artifact is not None:
                try:
                    if artifact.exists():
                        body = artifact.read_text().rstrip("\n")
                        self._write(_FENCE_BEGIN)
                        self._write(body)
                        self._write(_FENCE_END)
                except OSError:
                    pass
            stats = _stats_from_metrics(event.final_metrics)
            transition = self._transition_for(event)
            self._write(f"{_stage_tag(event.stage)}{transition} | {stats}")
        elif isinstance(event, RunEnd):
            stats = _stats_from_run_stats(event.aggregate_stats)
            if event.success:
                self._write(f"totals: {stats}")
            else:
                self._write(f"totals (failed): {stats}")
                if event.error:
                    self._write(f"error: {event.error}")
            self._flush()

    @staticmethod
    def _transition_for(event: StageEnd) -> str:
        """Stage transition label for the stats line.

        Spec §Console output cadence sample: ``done`` for non-review stages,
        ``approved`` for a successful review, ``handover → IMPLEMENT`` when a
        review fails (changes requested loops back to IMPLEMENT).

        For REVIEW, the verdict (approved vs changes_requested) lives in
        the parsed structured-output status block — ``StageEnd.success``
        only means "the stage executed without error". Prefer
        ``event.verdict`` when present; fall back to ``success`` for
        non-REVIEW stages or when no verdict was parsed.
        """
        if not event.success:
            if event.stage == StageName.REVIEW:
                return "handover → IMPLEMENT"
            return "failed"
        if event.stage == StageName.REVIEW:
            verdict = event.verdict
            if verdict == "changes_requested":
                return "handover → IMPLEMENT"
            if verdict == "approved":
                return "approved"
            # Unknown / None → fall back to legacy label so the renderer
            # stays useful for stages whose driver hasn't been updated.
            return "approved"
        return "done"

    # ── Subscriber Protocol ────────────────────────────────────────

    async def handle(self, event: ProgressEvent) -> None:
        if self._is_plain():
            await self._handle_plain(event)
            return
        # Legacy rich.Live path
        if isinstance(event, StageStart):
            self._stage_name = event.stage.value
            self._session_id = event.session_id
            self.recent_events.clear()
            self._live = Live(
                self._render(), console=self._console, refresh_per_second=1
            )
            self._live.__enter__()
        elif isinstance(event, StageEnd):
            if self._live is not None:
                self._live.update(self._render())
                self._live.__exit__(None, None, None)
                self._live = None
        elif isinstance(event, GroupOpen):
            self.recent_events.append(f"▶ {event.title}")
            self._refresh()
        elif isinstance(event, GroupClose):
            self.recent_events.append("◀ end")
            self._refresh()
        elif isinstance(event, ToolEntry):
            self.recent_events.append(f"[tool] {event.name} {event.target[:80]}")
            self._refresh()
        elif isinstance(event, Milestone):
            self.recent_events.append(f"✨ {event.label}")
            self._refresh()
        elif isinstance(event, Metrics):
            self._refresh()
        elif isinstance(event, RunEnd):
            # Legacy mode: ignore — pipeline-level totals aren't part of the
            # rich-pane UX.
            pass

    # ── Legacy rich.Live rendering ─────────────────────────────────

    def render_status_bar(self) -> str:
        s = self._state
        if s is None:
            return ""
        elapsed = int(s.snapshot_metrics().elapsed)
        return (
            f"stage: {self._stage_name} | "
            f"tokens: {s.input_tokens}/{s.output_tokens} | "
            f"cost: ${s.total_cost_usd:.2f} | "
            f"turns: {s.num_turns}/{s.max_turns} | "
            f"elapsed: {elapsed // 60}:{elapsed % 60:02d} | "
            f"session: {self._session_id}"
        )

    def _render(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="events", ratio=4),
            Layout(name="status", size=3),
        )
        events_text = "\n".join(self.recent_events)
        layout["events"].update(Panel(Text(events_text), title="Progress"))
        layout["status"].update(Panel(Text(self.render_status_bar())))
        return layout

    def _refresh(self) -> None:
        if self._live is not None:
            self._live.update(self._render())


__all__ = ["ConsoleSubscriber"]
