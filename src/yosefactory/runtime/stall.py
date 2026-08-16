"""The stall detector: absence is the predicate.

The failure this exists to catch is not a crash. It is a long run of green turns that produced
nothing, which is indistinguishable from a working factory to any check that looks for errors. So
the alarm condition is the *absence* of `advanced` in the window, not the presence of `failed` — a
window of nothing but `nothing-ready` is a stall and fires.

A gap fires for the same reason: a run whose record never arrived is a run whose outcome nobody
knows, and an unknown outcome that is silently skipped is how a broken factory reports success.

A non-progressing window is further classified as **starved** or **broken**, read from the recorded
reason on each position, never deduced from the window's shape. Starvation renames the alarm; it
never silences it — a factory permanently out of quota produces nothing, and this is `nothing-ready`
wearing a reason. A single position that is not starvation — a crash, a gap, an idle backlog — makes
the whole window broken, because the least informative position in the stream must not produce the
least alarming verdict.
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from yosefactory.protocol.turn import Outcome, counts_as_progress, starved
from yosefactory.runtime.config import DEFAULTS
from yosefactory.runtime.runs import Position, read_window


class Status(StrEnum):
    """One field, three values — not a `stalled` boolean beside a `starved` one.

    Two booleans invite a reader to check one and not the other, which is the exact failure this
    module exists to repair for the outcome enum itself.
    """

    OK = "ok"
    STALLED = "stalled"
    STARVED = "starved"


@dataclass(frozen=True, slots=True)
class Verdict:
    """What the detector saw. An alarm that says only "stalled" invites the reader to dismiss it."""

    status: Status
    window: int
    examined: int
    counts: dict[str, int]
    gaps: int
    last_advance: str | None
    reasons: dict[str, int]

    @property
    def stalled(self) -> bool:
        """Either alarm state. Both exit non-zero; this is for a caller that only asks whether."""
        return self.status is not Status.OK

    def report(self) -> str:
        seen = ", ".join(f"{name}={count}" for name, count in sorted(self.counts.items())) or "nothing"
        where = f"last advance at {self.last_advance}" if self.last_advance else "no advance anywhere in the stream"
        head = self.status.value.upper()
        reasons = ", ".join(f"{name}={count}" for name, count in sorted(self.reasons.items()))
        why = f"; reasons=[{reasons}]" if reasons else ""
        return f"{head}: window={self.window} examined={self.examined} [{seen}]{why} gaps={self.gaps}; {where}"


def evaluate(positions: list[Position], window: int, *, history: list[Position] | None = None) -> Verdict:
    counts = Counter(position.outcome.value for position in positions)
    gaps = sum(1 for position in positions if position.is_gap)
    progressed = any(counts_as_progress(position.outcome) for position in positions)
    advances = [p.slug for p in (history or positions) if not p.is_gap and p.outcome is Outcome.ADVANCED]

    reasons: dict[str, int] = {}
    status = Status.OK
    if not progressed:
        status = Status.STALLED
        if positions:
            # Starved requires every position to be an unattributable-free starvation failure: no
            # gap (no reason at all), no non-failure (free to try, produced nothing), no failure
            # whose reason is null or breakage. Any one of those makes the whole window broken.
            failure_kinds = [p.record.failure_kind if p.record is not None else None for p in positions if p.outcome is Outcome.FAILED]
            all_failed = len(failure_kinds) == len(positions)
            starvation_flags = [starved(kind) for kind in failure_kinds]
            reasons = dict(Counter(kind.value if kind else "unknown" for kind in failure_kinds))
            if all_failed and starvation_flags and all(starvation_flags):
                status = Status.STARVED

    return Verdict(
        status=status,
        window=window,
        examined=len(positions),
        counts=dict(counts),
        gaps=gaps,
        last_advance=advances[-1] if advances else None,
        reasons=reasons,
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
    return {Status.OK: 0, Status.STALLED: 1, Status.STARVED: 2}[verdict.status]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
