"""One-off driver: run `take_turn` for real, queue = this repo, workspace = a real a2web checkout.

Not a `src/yosefactory` module and not imported by anything — `openspec/changes/
run-a-turn-against-a2web` built this; `openspec/changes/score-d014-against-a2web` reuses it
unchanged except for `FRAME` and the `actor`/`owner` strings, targeting a different, still-open
a2web item (the prior FRAME's hepsiburada item is already committed to a2web, see that change's
design.md D1). Cross-repo `take_turn` has no CLI surface by design (`runtime.loop.main`'s own
docstring); this is the "caller that imports `run_loop` [`take_turn`] directly" that docstring
names.

Run inside the container, with the workspace path mounted separately from `/app`:

    docker compose run --rm -v ~/Workspaces/a2web:/data/a2web factory \\
        uv run python scripts/run_a2web_turn.py

Publication stays off (`publish_workspace=False, publish_queue=False`) — this run never pushes
either repository. No `BoardConfig` is constructed and no board module is imported — a2web's own
item text and file paths must never reach yosefactory's board.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from yosefactory.executor import claude
from yosefactory.protocol import backlog
from yosefactory.runtime.config import Guardrails
from yosefactory.runtime.isolation import IsolationPolicy
from yosefactory.runtime.turn import ITEMS, LOCK, RUNS, Places, append, new_item_id, take_turn

QUEUE = Path("/app")
WORKSPACE = Path("/data/a2web")

FRAME = {
    "goal": (
        "Verify and, if needed, fix bead a2web-luh: "
        "src/a2web/handlers/reddit.py's `reddit_forbidden_hint` (403 quarantined/NSFW/private, "
        "emitted around line 241) and `reddit_deleted_hint` (deleted/removed thread, emitted "
        "around line 924) both construct with no explicit severity, so they take OperatorHint's "
        "default 'info' — and `OperatorHint._omit_default_severity` drops the severity key from "
        "the wire entirely when it is 'info'. Both hints suggest trying an archive snapshot. "
        "Trace the terminal path: when the suggested archive fallback (`_archive_escalation_"
        "signal`, and old.reddit's own fallback in `_fetch_old_reddit_or_archive_signal`) ALSO "
        "fails, does the fetch end with a critical operator hint (try_user_browser or "
        "equivalent, per docs/adr/0009-never-silently-miss-a-url.md), or does it end carrying "
        "only the unescalated 'info' hint with no severity key on the wire at all? "
        "If it does not escalate, make it escalate. Add or extend a capability test covering the "
        "double-failure path (both the primary shape and the archive fallback fail) asserting a "
        "critical hint is present. Commit the result on a NEW branch (never `main`), with a real "
        "commit message following this repository's own convention (see CLAUDE.md/AGENTS.md/"
        "CONSTITUTION.md for the convention this workspace actually uses — read them, do not "
        "guess). Do not push."
    ),
    "method": (
        "Read src/a2web/handlers/reddit.py in full around both named emission sites and the "
        "escalation helpers they call, and docs/adr/0009-never-silently-miss-a-url.md, before "
        "changing anything. Read the existing reddit capability tests for the shape a new "
        "assertion should follow — do not invent a new test style. Create and check out a new "
        "branch before committing. Run `make check` yourself before proposing `done` if you can — "
        "the platform runs it again regardless as the actual gate."
    ),
    "assumptions": (
        "This is a real, already-acknowledged, standalone bug in this workspace's own backlog "
        "(bead a2web-luh, openspec/changes/flag-interaction-gated-sections/tasks.md §7.4) — it is "
        "not attached to any other in-flight change in this workspace, and its acceptance "
        "criterion is already stated on the bead: a Reddit fetch where both the primary shape and "
        "the archive fallback fail ends with a critical operator hint, covered by a capability "
        "test. This repository is not yours to push; a local commit on a new branch is the "
        "complete, correct outcome. If verification shows the terminal path already escalates "
        "correctly and only the test coverage is missing, adding the test alone is a legitimate, "
        "complete outcome — do not invent a code change the investigation does not support."
    ),
}


def main() -> int:
    item_id = new_item_id()
    item_path = QUEUE / ITEMS / f"{item_id}.jsonl"
    append(
        item_path,
        backlog.ITEM,
        {"event": "created", "loop": "default", "frame": FRAME},
        actor="yf-21",
    )
    print(f"seeded item: {item_id}", file=sys.stderr)

    places = Places(
        queue=QUEUE,
        ledger=QUEUE / RUNS,
        queue_lock=QUEUE / LOCK,
        workspace=WORKSPACE,
        workspace_lock=WORKSPACE / ".git" / "yosefactory-turn.lock",
        publish_workspace=False,
        publish_queue=False,
    )

    policy = IsolationPolicy(
        isolated=False,
        workspace_scoped=True,
        opt_out_reason=(
            "unattended run against a real foreign workspace inside the container; the container's "
            "mount topology (exactly {yosefactory, a2web}, nothing else) is what bounds what this "
            "run can reach, not this policy — see openspec/changes/run-a-turn-against-a2web/design.md D2"
        ),
    )

    def executor(frame, workspace, limits, *, run_id, runs_dir, invocation=None):
        return claude.run(frame, workspace, limits, run_id=run_id, runs_dir=runs_dir, invocation=invocation, policy=policy)

    limits = Guardrails(
        window=10,
        wall_clock_seconds=45 * 60,
        turn_ceiling=60,
        grace_seconds=30,
        question_deadline_hours=24,
        # Turn 1 hit the platform's own $2.50 ceiling (budget_exhausted, correctly enforced)
        # before committing, at $2.5365 spent. $2.40 for the retry: the remaining $2.46 of the
        # $5 standing allowance, with a small margin, not a widened scope.
        cost_ceiling_usd=2.40,
    )

    record = take_turn(
        places,
        executor,
        limits=limits,
        owner="yf-21",
        skill=Path("/app/workflows/turn-skill.md"),
        test_command=("make", "check"),
        # `take_turn`'s own `isolated` kwarg defaults to True and only feeds the record field --
        # separate from the `IsolationPolicy` actually handed to the executor above. `run_loop`
        # was fixed to wire this through (cb2d2fa); this direct call site was not, so turn 1's
        # record read "isolated": true for a run that was workspace_scoped + bypassPermissions
        # the whole time. Passing the real policy's own flag keeps the record honest.
        isolated=policy.isolated,
    )

    print(json.dumps(record.to_dict(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
