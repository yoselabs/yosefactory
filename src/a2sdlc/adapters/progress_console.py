"""Console progress adapter using rich.Live for local mode."""

from __future__ import annotations

import time
from collections import deque

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from a2sdlc.domain.models import StageName


class ConsoleProgressAdapter:
    """Live console renderer: scrolling events on top, status bar on bottom.

    Implements ProgressAdapter (see adapters/protocols.py).
    """

    _MAX_EVENTS = 20

    def __init__(self) -> None:
        self.active_stage: StageName | None = None
        self.session_id: str = ""
        self.recent_events: deque[str] = deque(maxlen=self._MAX_EVENTS)
        self._tokens_in = 0
        self._tokens_out = 0
        self._cost_usd = 0.0
        self._turns = 0
        self._started_at: float | None = None
        self._live: Live | None = None
        self._console = Console()

    def on_stage_start(self, stage: StageName, session_id: str) -> None:
        self.active_stage = stage
        self.session_id = session_id
        self.recent_events.clear()
        self._tokens_in = 0
        self._tokens_out = 0
        self._cost_usd = 0.0
        self._turns = 0
        self._started_at = time.monotonic()
        self._live = Live(self._render(), console=self._console, refresh_per_second=1)
        self._live.__enter__()

    def on_event(self, event_type: str, text: str) -> None:
        # Truncate very long text to one line-ish chunks
        preview = text.splitlines()[0][:200] if text else ""
        self.recent_events.append(f"[{event_type}] {preview}")
        if self._live is not None:
            self._live.update(self._render())

    def on_stage_end(self, stage: StageName, success: bool) -> None:
        if self._live is not None:
            self._live.__exit__(None, None, None)
            self._live = None

    def on_group_open(self, title: str) -> None:
        self.recent_events.append(f"\u25b6 {title}")
        if self._live is not None:
            self._live.update(self._render())

    def on_group_close(self) -> None:
        self.recent_events.append("\u25c0 end")
        if self._live is not None:
            self._live.update(self._render())

    def update_metrics(
        self, tokens_in: int, tokens_out: int, cost_usd: float, turns: int
    ) -> None:
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self._cost_usd = cost_usd
        self._turns = turns
        if self._live is not None:
            self._live.update(self._render())

    def render_status_bar(self) -> str:
        elapsed = (
            0 if self._started_at is None else int(time.monotonic() - self._started_at)
        )
        stage_name = self.active_stage.value if self.active_stage else "-"
        return (
            f"stage: {stage_name} | tokens: {self._tokens_in}/{self._tokens_out} | "
            f"cost: ${self._cost_usd:.2f} | turns: {self._turns} | "
            f"elapsed: {elapsed // 60}:{elapsed % 60:02d} | session: {self.session_id}"
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
