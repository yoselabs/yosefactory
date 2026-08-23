"""The `claude -p` lane: a version, a canary, and one bounded run.

Three of the four entry points the design names. `capabilities()` is deliberately absent — a
three-state capability map exists to reconcile executors that disagree, and with one executor it
degenerates into the union of whatever that executor does. It arrives with the second lane, when a
real disagreement can shape it. The rule that survives the deferral is enforced here anyway: an
absent capability must name the harness that emulates it, or the adapter does not register.

Neither a cost ceiling nor a wall clock exists in this binary, so both come from the supervisor.
There is no turn ceiling either — the flag that would set one is not in the pinned version, and
`num_turns` reaches us only in the terminal event, which is far too late to bound anything. The
count is therefore taken live from the stream and enforced by the supervisor.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yosefactory.executor.invocation import Invocation
from yosefactory.executor.outcome import FailureKind, RunOutcome, RunResult, Usage
from yosefactory.executor.stream import StreamReader
from yosefactory.protocol.turn import Outcome
from yosefactory.runtime.config import Guardrails
from yosefactory.runtime.isolation import IsolationPolicy
from yosefactory.runtime.supervise import Recorder, govern

# Behaviour is a property of the binary, not of this adapter, and it moves on point releases. A
# claim about what the executor can do is invalid unless it was checked against a pinned version.
PINNED_VERSION = "2.1.225"

# Denis's ruling, applied directly (pin-the-executor-and-close-the-push-grant): every invocation
# names an explicit model and effort rather than falling through to the binary's own default, which
# is what every run before this constant existed did — leaving no TurnRecord or ledger row able to
# say what produced its cost. Both flags exist at the pinned version, checked by running
# `claude --help` against the pinned binary itself rather than recalled from memory: `--model
# <model>` and `--effort <level>` (low, medium, high, xhigh, max).
PINNED_MODEL = "claude-sonnet-5"
PINNED_EFFORT = "medium"

# Capabilities this binary does not have, each naming what supplies it instead. An entry that names
# no emulation is a registration failure rather than a footnote, which is what stops a limit from
# being deferred indefinitely.
EMULATED: Mapping[str, str] = {
    "wall_clock": "harness: runtime.supervise.govern",
    "turn_ceiling": "harness: runtime.supervise.govern, counting post_turn_summary events",
}

# Native at the pinned version, measured by running it rather than by reading help text. `cost_ceiling`
# was in EMULATED above, declared absent, against a binary that has had `--max-budget-usd` all along —
# a capability claim checked against nothing, which is what §7b rule 4 forbids. `build_argv` now sends
# it when `Guardrails.cost_ceiling_usd` is set. It bounds the turn that crossed the line rather than
# the next one, so it detects overspend and does not prevent it: measured $0.048 against a $0.02 cap
# — see `claude-executor/cost-ceiling`, which states the detector-not-ceiling distinction normatively.
NATIVE: Mapping[str, str] = {
    "cost_ceiling": "claude --max-budget-usd; post-turn, so overshoot is bounded by one turn's cost",
}

_VERSION = re.compile(r"(\d+\.\d+\.\d+)")
_EXIT = re.compile(r"exit=(-?\d+)")
_CANARY_TIMEOUT_SECONDS = 60


class ExecutorError(RuntimeError):
    """The lane may not be used as configured."""


@dataclass(frozen=True, slots=True)
class Preflight:
    ok: bool
    version: str
    reason: str = ""
    failure_kind: FailureKind | None = None

    def report(self) -> str:
        headline = "preflight ok" if self.ok else "PREFLIGHT FAILED"
        return f"{headline} (claude {self.version or 'unknown'})" + (f": {self.reason}" if self.reason else "")


def _binary() -> str:
    found = shutil.which("claude")
    if found is None:
        raise ExecutorError("claude is not on PATH")
    return found


def resolve_version() -> str:
    """Asks the binary. Never inferred from a package pin, which describes a different artifact."""
    completed = subprocess.run([_binary(), "--version"], capture_output=True, text=True, check=False)  # noqa: S603
    match = _VERSION.search(completed.stdout)
    if match is None:
        raise ExecutorError("claude --version did not report a version")
    return match.group(1)


def registration_gaps() -> tuple[str, ...]:
    return tuple(name for name, emulation in EMULATED.items() if not emulation)


def preflight(*, expect_version: str = PINNED_VERSION) -> Preflight:
    """Once per job, never per turn.

    A credential that expired silently is otherwise indistinguishable from a task the agent could
    not do, and the two have opposite fixes. Expiry behaviour is not documented consistently, so it
    is checked rather than assumed. The canary is not free — it pays a full cold cache — which is
    exactly why it runs once for a job rather than once for each of its turns.
    """
    gaps = registration_gaps()
    if gaps:
        raise ExecutorError(f"capabilities without a declared emulation may not register: {', '.join(gaps)}")

    version = resolve_version()
    if version != expect_version:
        return Preflight(ok=False, version=version, reason=f"expected {expect_version}", failure_kind=FailureKind.VERSION_MISMATCH)

    argv = [_binary(), "-p", "Reply with exactly: OK", "--output-format", "json", "--strict-mcp-config"]
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=_CANARY_TIMEOUT_SECONDS, check=False)  # noqa: S603
    except subprocess.TimeoutExpired:
        return Preflight(ok=False, version=version, reason="the canary did not answer", failure_kind=FailureKind.CRASH)

    reader = StreamReader(Path("/dev/null"))
    reader.consume(completed.stdout.strip() or "{}")
    outcome, kind, detail = reader.classify(completed.returncode)
    if outcome is not RunOutcome.SUCCESS:
        return Preflight(ok=False, version=version, reason=detail or outcome.value, failure_kind=kind)
    return Preflight(ok=True, version=version)


def build_argv(
    prompt: str,
    policy: IsolationPolicy,
    *,
    cost_ceiling_usd: float | None = None,
    model: str = PINNED_MODEL,
    effort: str = PINNED_EFFORT,
) -> list[str]:
    """Policy becomes invocation here, and nowhere else.

    `model`/`effort` are sent on every call, never omitted -- unlike `cost_ceiling_usd`, whose
    absence is a real, distinct state ("no ceiling requested"). A run has no "unrequested" model:
    a caller that states no opinion still gets the pinned default (`PINNED_MODEL`/`PINNED_EFFORT`),
    not a binary default nothing here would ever see.

    Three flags, each measured against the init event rather than taken from help text — which is the
    whole lesson of how this set was arrived at. `--strict-mcp-config` and `--permission-mode` were
    the previous isolated posture and they isolate nothing: an agent run under them reports the host's
    memory, the host's skills and the repository's own skills and agents as loaded.

    Safe mode is what isolates. It is also a floor rather than a base to build on: an explicit
    `--mcp-config` passed alongside it is ignored, which is why the policy refuses that combination
    instead of emitting arguments that would silently do nothing. Opting out is therefore a different
    invocation, not this one with additions.

    Bare mode is never emitted in either posture: it skips repository configuration and also declines
    to read the subscription credential, so on a subscription it buys isolation by making the run
    unable to authenticate at all.

    `workspace_scoped` is neither branch above: `--setting-sources project,local`, no `--safe-mode`.
    Measured (`scope-isolation-by-config-source`) to admit the working repository's own `CLAUDE.md`,
    settings, skills and `.mcp.json` while excluding the host's user-level `CLAUDE.md`, skills,
    plugins and `settings.json`-declared MCP servers. It is a genuinely different mechanism from
    `isolated`, not a lighter version of it — the policy already refuses the two together because
    safe mode zeroes `--setting-sources` regardless of its value. It also carries
    `--permission-mode bypassPermissions` (`run-the-loop-inside-the-container`): this posture is
    the one an unattended run uses, and a posture that admits repository configuration but still
    gates every tool call on a human who is not there fails exactly the way the old unconditional
    `isolated` default failed.

    `cost_ceiling_usd` is orthogonal to the posture and sent in both branches when set. Absent, no
    flag is emitted — a ceiling is never substituted on the caller's behalf.
    """
    argv = [_binary(), "-p", prompt, "--output-format", "stream-json", "--verbose", "--model", model, "--effort", effort]
    if cost_ceiling_usd is not None:
        argv += ["--max-budget-usd", str(cost_ceiling_usd)]
    if policy.isolated:
        # Approval must fail rather than wait: there is no human to answer it.
        argv += ["--safe-mode", "--strict-mcp-config", "--disable-slash-commands", "--permission-mode", "manual"]
    else:
        # Repository configuration loads under -p with no trust dialog, so an opted-out run pins what
        # it admits rather than inheriting it.
        argv += ["--strict-mcp-config"]
        if policy.workspace_scoped:
            # Carte blanche inside the workspace, per Denis's ruling (run-the-loop-inside-the-
            # container): workspace_scoped exists for unattended runs, and an invocation that
            # still gates every tool call on human approval fails the same way the old
            # unconditional `isolated` default did. bypassPermissions is the policy half of the
            # boundary; the container's mount topology (not this flag) is the other half.
            argv += ["--setting-sources", "project,local", "--permission-mode", "bypassPermissions"]
        if policy.settings_path:
            argv += ["--settings", policy.settings_path]
        if policy.mcp_config_path:
            argv += ["--mcp-config", policy.mcp_config_path]
        if policy.allowed_tools:
            argv += ["--allowedTools", *policy.allowed_tools]
    return argv


def _render_context(context: Mapping[str, Any]) -> str:
    """D030's second channel, rendered after the frame and before `invocation`'s plumbing --
    content before plumbing, same order the frame/invocation split already keeps. Each of
    `backlog.context()`'s four possible keys gets one line, only when present.
    """
    lines = ["Inherited context from a prior attempt:"]
    if "gate_rejection" in context:
        lines.append(f"- gate rejected: {context['gate_rejection']['report']}")
    if "answer" in context:
        lines.append(f"- answered: {context['answer']}")
    if "prior_failure" in context:
        pf = context["prior_failure"]
        lines.append(f"- prior attempt failed: {pf['reason']} (retryable: {pf['retryable']})")
    if "ended" in context:
        ended = context["ended"]
        lines.append(f"- previous attempt ended ({ended['event']}): {ended['reason']}")
    return "\n".join(lines)


def render(frame: Mapping[str, Any], context: Mapping[str, Any] | None = None, invocation: Invocation | None = None) -> str:
    """D019's three fields, in a stable order so two runs of one frame are comparable.

    Every other key in `frame` is dropped, and that is the point: the frame is what the work *is*,
    and it is compared across runs. How to run it travels in `invocation` instead, so plumbing never
    enters the item's trail (see `executor.invocation`).

    `context` (D030) sits between the two: what attempts before this one produced, folded from the
    item's own log (`backlog.context()`). Rendered only when non-empty, so a first attempt's prompt
    is unchanged from before this parameter existed.
    """
    parts = [f"{key}: {frame[key]}" for key in ("goal", "method", "assumptions") if frame.get(key)]
    if not parts:
        raise ExecutorError("a frame must carry at least a goal")
    if context:
        parts.append(_render_context(context))
    rendered = invocation.render() if invocation is not None else ""
    return "\n".join([*parts, rendered]) if rendered else "\n".join(parts)


def _usage(terminal: dict[str, Any] | None) -> Usage:
    if terminal is None:
        return Usage()
    raw = terminal.get("usage") or {}
    return Usage(
        input_tokens=int(raw.get("input_tokens", 0)),
        output_tokens=int(raw.get("output_tokens", 0)),
        cache_creation_input_tokens=int(raw.get("cache_creation_input_tokens", 0)),
        cache_read_input_tokens=int(raw.get("cache_read_input_tokens", 0)),
        total_cost_usd=float(terminal.get("total_cost_usd", 0.0) or 0.0),
        num_turns=int(terminal.get("num_turns", 0)),
    )


def run(
    frame: Mapping[str, Any],
    workspace: Path,
    limits: Guardrails,
    *,
    run_id: str,
    runs_dir: Path,
    context: Mapping[str, Any] | None = None,
    invocation: Invocation | None = None,
    recorder: Recorder | None = None,
    policy: IsolationPolicy | None = None,
    turn_ceiling: int | None = None,
    model: str = PINNED_MODEL,
    effort: str = PINNED_EFFORT,
) -> RunResult:
    """One bounded invocation, and a result derived from the agent's own terminal event.

    The transcript is written inside the run stream rather than into the workspace. That is what
    makes `dirty` mean what it claims: the supervisor excludes its own stream by construction, so
    the harness's evidence of a run can never be mistaken for the agent having left work half-done.

    `model`/`effort` default to the pinned values and are always sent (`build_argv`). The
    `RunResult` returned reports `model` from the run's own `system|init` event when one was
    captured -- the stronger receipt, the agent stating what it actually ran -- and falls back to
    the requested value only when no init event exists at all (a run that failed before startup).
    `effort` is not reported by any event this binary's stream carries at the pinned version
    (measured: absent from `init`, from every `assistant` message, and from the terminal `result`),
    so it is always recorded from what was requested -- a weaker receipt, stated as such rather than
    conflated with `model`'s.
    """
    policy = policy or IsolationPolicy()
    transcript = runs_dir / f"{run_id}.stream.jsonl"
    reader = StreamReader(transcript)

    def verdict() -> Outcome | None:
        reader.poll()
        if reader.terminal is None:
            return None
        outcome, _, _ = reader.classify(None)
        return RunResult(outcome=outcome, usage=Usage(), transcript_path=transcript, exit_code=None, dirty=False).protocol_outcome

    record = govern(
        build_argv(
            render(frame, context, invocation), policy, cost_ceiling_usd=limits.cost_ceiling_usd, model=model, effort=effort
        ),
        repo=workspace,
        runs_dir=runs_dir,
        run_id=run_id,
        guard=limits,
        turn_ceiling=limits.turn_ceiling if turn_ceiling is None else turn_ceiling,
        isolated=policy.isolated,
        turns_taken=reader.turns_taken,
        verdict=verdict,
        stdout=transcript,
        recorder=recorder,
    )

    exit_match = _EXIT.search(record.note)
    exit_code = int(exit_match.group(1)) if exit_match else None
    outcome, kind, detail = reader.classify(exit_code)

    if policy.isolated and reader.init is not None and reader.init.leaks:
        # The agent reported loading host configuration an isolated run must not see. Its work is
        # not trustworthy as isolated, and reporting the run's own verdict here would hide that.
        outcome, kind = RunOutcome.FAILED, FailureKind.TASK_ERROR
        detail = "isolation breached: " + ", ".join(reader.init.leaks)
    elif policy.workspace_scoped and reader.init is not None and reader.init.workspace_scope_leaks:
        # workspace_scoped admits the repository's own skills, memory and mcp servers by design, so
        # `leaks` (built for the isolated posture's leaks==() assertion) does not apply here. What is
        # measured absent under --setting-sources project,local is host plugin registration: a
        # non-empty `plugins` list means the run did not actually get the workspace-scoped sources.
        outcome, kind = RunOutcome.FAILED, FailureKind.TASK_ERROR
        detail = "workspace scope breached: " + ", ".join(reader.init.workspace_scope_leaks)

    usage = _usage(reader.terminal)
    # Cost recording moved to `runtime.turn` (commit-the-spend-row-inside-the-turn): the row must
    # land in `places.queue`, which this function has no way to name (it sees `runs_dir`, not the
    # `Places` that produced it), and must be committed in the same transaction as the run record
    # `turn.py` writes after this call returns -- not written out-of-band here and left for a
    # later, unrelated commit to maybe pick up. `result.usage.total_cost_usd` below is what
    # `turn._dispose` reads to do that, for every executor, not just this one.

    # Prefer what the agent reported loading over what we asked for -- the init event is evidence,
    # the argument is only intent (same instrument `leaks`/`workspace_scope_leaks` already trust).
    # Falls back to the requested value only when no init event was ever captured.
    reported_model = reader.init.model if reader.init is not None and reader.init.model else model

    return RunResult(
        outcome=outcome,
        usage=usage,
        transcript_path=transcript,
        exit_code=exit_code,
        dirty=record.dirty,
        failure_kind=kind,
        detail=detail,
        model=reported_model,
        effort=effort,
    )
