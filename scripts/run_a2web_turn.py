"""One-off driver: run `take_turn` for real, queue = this repo, workspace = a real a2web checkout.

Not a `src/yosefactory` module and not imported by anything — `openspec/changes/
run-a-turn-against-a2web` is the change this exists for. Cross-repo `take_turn` has no CLI surface
by design (`runtime.loop.main`'s own docstring); this is the "caller that imports `run_loop`
[`take_turn`] directly" that docstring names.

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
        'Add "hepsiburada.com" to `_JS_HEAVY_HOSTS_SEED` in '
        "src/a2web/fetcher/comprehension/gate.py, the frozenset of JS-heavy CSR hosts (already "
        'contains "trendyol.com", "aliexpress.com" — follow that pattern exactly, keep the set '
        "sorted the way it already is or append at the end, no reordering of the existing entries). "
        "Add one matching test assertion to tests/capabilities/quality_gate/test_gate.py "
        "confirming hepsiburada.com is now included (follow the existing test's own shape for "
        "trendyol.com/aliexpress.com in that file — do not invent a new test style). Commit the "
        "result on a NEW branch (never `main`), with a real commit message following this "
        "repository's own convention (see CLAUDE.md/AGENTS.md/CONSTITUTION.md for the convention "
        "this workspace actually uses — read them, do not guess). Do not push."
    ),
    "method": (
        "Read src/a2web/fetcher/comprehension/gate.py and "
        "tests/capabilities/quality_gate/test_gate.py first. Create and check out a new branch "
        "before committing. Run `make check` yourself before proposing `done` if you can — the "
        "platform runs it again regardless as the actual gate."
    ),
    "assumptions": (
        "This is a real, already-acknowledged, standalone follow-up item in this workspace's own "
        "backlog (bead a2web-cid, openspec/changes/flag-interaction-gated-sections/tasks.md §7.5) "
        "— it is not attached to any other in-flight change in this workspace, and touching only "
        "the two named files is expected to be self-contained. This repository is not yours to "
        "push; a local commit on a new branch is the complete, correct outcome."
    ),
}


def main() -> int:
    item_id = new_item_id()
    item_path = QUEUE / ITEMS / f"{item_id}.jsonl"
    append(
        item_path,
        backlog.ITEM,
        {"event": "created", "loop": "default", "frame": FRAME},
        actor="yf-19",
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
        cost_ceiling_usd=2.50,
    )

    record = take_turn(
        places,
        executor,
        limits=limits,
        owner="yf-19",
        skill=Path("/app/workflows/turn-skill.md"),
        test_command=("make", "check"),
    )

    print(json.dumps(record.to_dict(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
