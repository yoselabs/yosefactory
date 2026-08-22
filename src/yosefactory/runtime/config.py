"""Guardrail thresholds, read from `[tool.yosefactory.guardrails]` in pyproject.toml.

Thresholds are tuning, not protocol: moving them does not make an existing record incomparable to an
older one, so they live in config rather than in `protocol/`. No config surface accepts a token, a
credential, or a path.
"""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

# N and the wall clock are guesses. There is no traffic yet to choose them from, and D021's posture
# is explicitly build the detector, learn the condition, decide the limit later. The wall clock is
# set well under the six-hour ceiling hosted CI applies, so the harness stop is always the one that
# fires first.
DEFAULTS: Final[dict[str, int]] = {
    "window": 10,
    "wall_clock_seconds": 45 * 60,
    "turn_ceiling": 40,
    "grace_seconds": 20,
    # A question's `deadline` is required by the format — there is no "send nothing" state the way
    # `cost_ceiling_usd` has one, so this is a guess with a default like its four siblings above,
    # not `_OPTIONAL` below.
    "question_deadline_hours": 24,
    # unstick-the-backlog / S1021: how many times a lease may expire (or a `failed` proposal may
    # land) on the same item before the reclaim sweep poisons it instead of reclaiming it again. A
    # guess, like its siblings above -- D021's posture is build the detector, learn the condition,
    # decide the limit later.
    "max_attempts": 3,
}

_SECRET_ISH: Final = ("token", "key", "secret", "password", "credential", "path", "home")

# Not in `DEFAULTS`: its default is `None`, meaning "send no flag," and folding it into `DEFAULTS`
# would make every config load supply a value the caller never asked for.
_OPTIONAL: Final = ("cost_ceiling_usd",)


class ConfigError(ValueError):
    """The guardrail config may not be used as written."""


@dataclass(frozen=True, slots=True)
class Guardrails:
    window: int
    wall_clock_seconds: int
    turn_ceiling: int
    grace_seconds: int
    question_deadline_hours: int
    max_attempts: int
    # None means no flag is sent, not "no limit substituted on the caller's behalf" — the executor
    # must not pick a number nobody asked for. When set, it is a post-turn detector: the binary checks
    # after a turn completes and stops the next one, so the turn that crosses the line still finishes.
    cost_ceiling_usd: float | None = None

    def __post_init__(self) -> None:
        for name in ("window", "wall_clock_seconds", "turn_ceiling", "grace_seconds", "question_deadline_hours", "max_attempts"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ConfigError(f"{name} must be a positive integer, got {value!r}")
        if self.wall_clock_seconds >= 6 * 60 * 60:
            raise ConfigError("wall_clock_seconds must sit well under the six-hour CI ceiling, or CI stops the run first")
        if self.cost_ceiling_usd is not None:
            ceiling = self.cost_ceiling_usd
            valid = isinstance(ceiling, (int, float)) and not isinstance(ceiling, bool) and math.isfinite(ceiling) and ceiling > 0
            if not valid:
                raise ConfigError(f"cost_ceiling_usd must be a positive finite number or None, got {ceiling!r}")


def from_mapping(table: dict[str, Any]) -> Guardrails:
    unknown = [key for key in table if key not in DEFAULTS and key not in _OPTIONAL]
    if unknown:
        raise ConfigError(f"unknown guardrail setting(s): {', '.join(sorted(unknown))}")
    smells = [key for key in table if any(hint in key.lower() for hint in _SECRET_ISH)]
    if smells:
        raise ConfigError(f"guardrail config carries no secrets or paths; refused: {', '.join(sorted(smells))}")
    merged = {**DEFAULTS, **table}
    return Guardrails(**merged)


def load(pyproject: Path) -> Guardrails:
    if not pyproject.is_file():
        return Guardrails(**DEFAULTS)
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    table = data.get("tool", {}).get("yosefactory", {}).get("guardrails", {})
    return from_mapping(dict(table))
