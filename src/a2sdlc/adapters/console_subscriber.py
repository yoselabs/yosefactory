"""ConsoleSubscriber — rich.Live renderer driven by ProgressEvent stream."""

from __future__ import annotations

from collections import deque

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from a2sdlc.evaluation.progress import (
    GroupClose,
    GroupOpen,
    Metrics,
    Milestone,
    ProgressEvent,
    ProgressState,
    StageEnd,
    StageStart,
    ToolEntry,
)


class ConsoleSubscriber:
    """Live console: scrolling events on top, status bar on bottom.

    Status bar reads counters off the shared ``ProgressState`` so the values
    are always current — no private state to keep in sync.
    """

    _MAX_EVENTS = 20

    def __init__(self, state: ProgressState) -> None:
        self._state = state
        self.recent_events: deque[str] = deque(maxlen=self._MAX_EVENTS)
        self._stage_name: str = "-"
        self._session_id: str = ""
        self._live: Live | None = None
        self._console = Console()

    async def handle(self, event: ProgressEvent) -> None:
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
            self.recent_events.append(f"\u25b6 {event.title}")
            self._refresh()
        elif isinstance(event, GroupClose):
            self.recent_events.append("\u25c0 end")
            self._refresh()
        elif isinstance(event, ToolEntry):
            self.recent_events.append(f"[tool] {event.name} {event.target[:80]}")
            self._refresh()
        elif isinstance(event, Milestone):
            self.recent_events.append(f"\u2728 {event.label}")
            self._refresh()
        elif isinstance(event, Metrics):
            self._refresh()  # status bar reads from state — just trigger redraw

    def render_status_bar(self) -> str:
        s = self._state
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
