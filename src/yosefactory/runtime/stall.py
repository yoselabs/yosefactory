"""The stall detector: absence is the predicate.

The failure this exists to catch is not a crash. It is a long run of green turns that produced
nothing, which is indistinguishable from a working factory to any check that looks for errors. So
the alarm condition is the *absence* of `advanced` in the window, not the presence of `failed` — a
window of nothing but `nothing-ready` is a stall and fires.

A gap fires for the same reason: a run whose record never arrived is a run whose outcome nobody
knows, and an unknown outcome that is silently skipped is how a broken factory reports success.
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from yosefactory.protocol.turn import Outcome, counts_as_progress
from yosefactory.runtime.config import DEFAULTS
from yosefactory.runtime.runs import Position, read_window


@dataclass(frozen=True, slots=True)
class Verdict:
    """What the detector saw. An alarm that says only "stalled" invites the reader to dismiss it."""

    stalled: bool
    window: int
    examined: int
    counts: dict[str, int]
    gaps: int
    last_advance: str | None

    def report(self) -> str:
        seen = ", ".join(f"{name}={count}" for name, count in sorted(self.counts.items())) or "nothing"
        where = f"last advance at {self.last_advance}" if self.last_advance else "no advance anywhere in the stream"
        head = "STALLED" if self.stalled else "ok"
        return f"{head}: window={self.window} examined={self.examined} [{seen}] gaps={self.gaps}; {where}"


def evaluate(positions: list[Position], window: int, *, history: list[Position] | None = None) -> Verdict:
    counts = Counter(position.outcome.value for position in positions)
    gaps = sum(1 for position in positions if position.is_gap)
    stalled = not any(counts_as_progress(position.outcome) for position in positions)
    advances = [p.slug for p in (history or positions) if not p.is_gap and p.outcome is Outcome.ADVANCED]
    return Verdict(
        stalled=stalled,
        window=window,
        examined=len(positions),
        counts=dict(counts),
        gaps=gaps,
        last_advance=advances[-1] if advances else None,
    )


def detect(runs_dir: Path, window: int = DEFAULTS["window"]) -> Verdict:
    """Read the stream and judge it. Invocable with no run in progress — that is the point."""
    everything = read_window(runs_dir, size=max(window, 10_000))
    return evaluate(everything[-window:], window, history=everything)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    runs_dir = Path(args[0]) if args else Path("ledger") / "runs"
    window = int(args[1]) if len(args) > 1 else DEFAULTS["window"]
    verdict = detect(runs_dir, window)
    sys.stdout.write(verdict.report() + "\n")
    return 1 if verdict.stalled else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
