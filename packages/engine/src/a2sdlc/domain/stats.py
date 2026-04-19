"""StageRunStats — accumulator for cost/tokens/duration across retries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from a2sdlc.domain.run_result import RunResult


@dataclass
class StageRunStats:
    """Accumulates cost, tokens, duration, and turns across stage run retries."""

    cost_usd: float = 0
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0
    num_turns: int = 0

    def add_from_result(self, result: RunResult) -> None:
        """Sum all fields from a RunResult into this accumulator."""
        self.cost_usd += result.total_cost_usd
        self.tokens_in += result.input_tokens
        self.tokens_out += result.output_tokens
        self.duration_ms += result.duration_ms
        self.num_turns += result.num_turns

    def reset(self) -> None:
        """Zero all accumulated fields."""
        self.cost_usd = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.duration_ms = 0
        self.num_turns = 0
