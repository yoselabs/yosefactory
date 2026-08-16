"""The isolation policy, and a preflight that checks the two things the policy cannot enforce itself.

Policy only. Turning a policy into executor invocation arguments belongs to the per-vendor wrapper
(D021), so nothing here spawns anything.

Two traps are encoded rather than commented:

- **Bare mode is never selected, in either posture.** It skips repository config *and* does not read
  the subscription OAuth credential, so on a subscription bare mode and authentication are mutually
  exclusive. A policy that reaches for it produces a run that cannot authenticate, surfacing as an
  unexplained refusal rather than a configuration error.
- **A run must not be suspendable by an approval prompt.** Measured true on this fleet today; that
  is a property of the current session mode, not of the design, and it reopens silently if the mode
  changes. A run suspended on a prompt nobody will answer is indistinguishable from a hang.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

# User-level agent configuration that must not be present in the home the agent runs under. The
# runner's home is empty by accident today; asserting it makes the guarantee deliberate.
USER_CONFIG_MARKERS: tuple[str, ...] = (".claude", ".claude.json", ".codex", ".config/yosefactory")


class Reason(StrEnum):
    """Why a preflight answered as it did. A code, never a path — this repository is public."""

    CLEAN = "clean"
    USER_CONFIG_PRESENT = "user-config-present"
    HOME_UNSET = "home-unset"
    PROMPT_CAN_SUSPEND = "prompt-can-suspend"


class IsolationError(RuntimeError):
    """A policy that may not be used."""


@dataclass(frozen=True, slots=True)
class IsolationPolicy:
    """Default isolated. Opting out is explicit and is never reached by omission."""

    isolated: bool = True
    settings_path: str | None = None
    mcp_config_path: str | None = None
    allowed_tools: tuple[str, ...] = ()
    opt_out_reason: str = ""

    def __post_init__(self) -> None:
        if not self.isolated and not self.opt_out_reason:
            raise IsolationError("running without isolation requires an explicit stated reason; omission is not an opt-out")

    @property
    def uses_bare_mode(self) -> bool:
        """Always false, and asserted by test. Bare mode cannot carry subscription auth."""
        return False


@dataclass(frozen=True, slots=True)
class PreflightResult:
    ok: bool
    reasons: tuple[Reason, ...] = field(default=(Reason.CLEAN,))

    def report(self) -> str:
        return ("preflight ok" if self.ok else "PREFLIGHT FAILED") + ": " + ", ".join(reason.value for reason in self.reasons)


def resolve(setting: bool | None = None, *, opt_out_reason: str = "") -> IsolationPolicy:
    """Absent configuration means isolated. There is no path where omission produces an opt-out."""
    if setting is None or setting is True:
        return IsolationPolicy(isolated=True)
    return IsolationPolicy(isolated=False, opt_out_reason=opt_out_reason)


def home_is_clean(home: Path | None = None) -> tuple[bool, Reason]:
    raw = os.environ.get("HOME") if home is None else str(home)
    if not raw:
        return False, Reason.HOME_UNSET
    root = Path(raw)
    for marker in USER_CONFIG_MARKERS:
        if (root / marker).exists():
            return False, Reason.USER_CONFIG_PRESENT
    return True, Reason.CLEAN


def prompts_cannot_suspend(interactive: bool | None = None) -> tuple[bool, Reason]:
    """A prompt must fail and return a denial rather than waiting for a human who is not there."""
    if interactive is None:
        interactive = os.environ.get("YOSEFACTORY_INTERACTIVE", "") == "1"
    return (False, Reason.PROMPT_CAN_SUSPEND) if interactive else (True, Reason.CLEAN)


def preflight(home: Path | None = None, *, interactive: bool | None = None) -> PreflightResult:
    """Boolean plus reason codes. Never emits the home path, in either result."""
    reasons: list[Reason] = []
    for ok, reason in (home_is_clean(home), prompts_cannot_suspend(interactive)):
        if not ok:
            reasons.append(reason)
    return PreflightResult(ok=not reasons, reasons=tuple(reasons) if reasons else (Reason.CLEAN,))
