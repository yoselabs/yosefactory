"""The isolation policy, and a preflight that checks the two things the policy cannot enforce itself.

Policy only. Turning a policy into executor invocation arguments belongs to the per-vendor wrapper
(D021), so nothing here spawns anything.

Three measurements are encoded rather than commented, all taken against claude 2.1.225:

- **Bare mode is never selected, in either posture.** It skips repository config *and* does not read
  the subscription OAuth credential, so on a subscription bare mode and authentication are mutually
  exclusive. A policy that reaches for it produces a run that cannot authenticate, surfacing as an
  unexplained refusal rather than a configuration error.
- **An emptied home is the same trap by another route.** The subscription credential lives in the
  host keychain under `$HOME`, so a run given a fresh home does not find a missing credential — it
  cannot look. Measured: `Not logged in`, no turn, zero cost. The old form of this preflight asserted
  that the home was *empty*, which asserted the run could not authenticate. It now asserts the
  opposite, and that inversion is the finding: an assertion is a claim about the world, and running
  it is the only thing that makes it a measurement.
- **A run must not be suspendable by an approval prompt.** Measured true on this fleet today; that
  is a property of the current session mode, not of the design, and it reopens silently if the mode
  changes. A run suspended on a prompt nobody will answer is indistinguishable from a hang.

The isolated posture is a floor rather than a baseline to add to: the executor's safe mode ignores
explicit re-admission of tool servers, so a policy that is isolated *and* names one describes a run
that would silently not have it. That combination is refused here rather than dropped quietly.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

# Where the subscription credential can be reached from, per platform. Presence of the store is what
# is checked; its contents are never read, and neither is ever emitted.
_MACOS_CREDENTIAL_STORE = "Library/Keychains"
_POSIX_CREDENTIAL_STORE = ".claude/.credentials.json"


class Reason(StrEnum):
    """Why a preflight answered as it did. A code, never a path — this repository is public."""

    CLEAN = "clean"
    HOME_UNSET = "home-unset"
    CREDENTIAL_UNREACHABLE = "credential-unreachable"
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
        if self.isolated and self.mcp_config_path:
            raise IsolationError("the isolated posture ignores an explicit tool-server config; it silently would not be there")

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


def credential_is_reachable(home: Path | None = None) -> tuple[bool, Reason]:
    """The home the agent runs under must be one the credential store can be found from.

    Isolation is never bought by moving the home. It does not work — the run stops before it starts —
    and it was never the right instrument anyway: an emptied home hides the user's configuration and
    leaves the repository's untouched, which is one of three leak surfaces.
    """
    raw = os.environ.get("HOME") if home is None else str(home)
    if not raw:
        return False, Reason.HOME_UNSET
    store = _MACOS_CREDENTIAL_STORE if sys.platform == "darwin" else _POSIX_CREDENTIAL_STORE
    if not (Path(raw) / store).exists():
        return False, Reason.CREDENTIAL_UNREACHABLE
    return True, Reason.CLEAN


def prompts_cannot_suspend(interactive: bool | None = None) -> tuple[bool, Reason]:
    """A prompt must fail and return a denial rather than waiting for a human who is not there."""
    if interactive is None:
        interactive = os.environ.get("YOSEFACTORY_INTERACTIVE", "") == "1"
    return (False, Reason.PROMPT_CAN_SUSPEND) if interactive else (True, Reason.CLEAN)


def preflight(home: Path | None = None, *, interactive: bool | None = None) -> PreflightResult:
    """Boolean plus reason codes. Never emits the home path, in either result."""
    reasons: list[Reason] = []
    for ok, reason in (credential_is_reachable(home), prompts_cannot_suspend(interactive)):
        if not ok:
            reasons.append(reason)
    return PreflightResult(ok=not reasons, reasons=tuple(reasons) if reasons else (Reason.CLEAN,))
