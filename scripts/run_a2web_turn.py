"""One-off driver: run `take_turn` for real, queue = this repo, workspace = a real a2web checkout.

Not a `src/yosefactory` module and not imported by anything — `openspec/changes/
run-a-turn-against-a2web` built this; `score-d014-against-a2web`, `score-d014-second-attempt`, and
now `the-platform-delivers-the-workspace-commit` reuse it unchanged except for `FRAME` and the
`actor`/`owner` strings, each targeting a different, still-open a2web item. Two beads tried and
dropped for this run before landing on the one below, both verified against a2web's own git log
rather than trusted from its `bd` listing: `a2web-qgo` is already committed at `e778fd9` (a prior
turn's work); `a2web-luh` reads open in `bd` but is already solved on `fix-reddit-archive-rescue-
escalation` at `9e183e4` (`git merge-base --is-ancestor 9e183e4 HEAD` on `e778fd9` is false — that
branch never merged) — the run under that frame burned $2.5073 to `budget_exhausted` without
reaching the gate (a2web-luh needs roughly $4.93 across two turns historically, well past one
turn's ceiling). Landed on a deliberately small slice of `a2web-2yd` instead. Cross-repo `take_turn`
has no CLI surface by design (`runtime.loop.main`'s own docstring); this is the "caller that imports
`run_loop` [`take_turn`] directly" that docstring names.

This run is this change's Article XVI receipt: proving `_deliver_workspace` amends a real workspace
boundary commit with both platform trailers, and that `Yosefactory-Run` on that commit resolves to
a real row in this repo's ledger — not that the a2web task itself is significant.

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
        "Implement a deliberately narrow slice of bead a2web-2yd: 'the eval capture harness has no "
        "CI coverage'. Do NOT attempt the whole bead — `eval/_capture/capture.py` is a live-network "
        "async orchestrator and out of scope here. The slice: `eval/_capture/corpus.py`'s own error "
        "paths (`CorpusError`) have no direct unit test anywhere in `tests/` today (verified: every "
        "test that touches `load_case`/`load_corpus` does so indirectly, through real fixture "
        "corpora, never exercising the guard clauses themselves). Add direct unit tests for: "
        "`load_case` raising `CorpusError` when a case directory has no `case.yaml`; `load_case` "
        "raising `CorpusError` when `case.yaml` is missing the required `slug` or `url` field; "
        "`_read_yaml`/`load_case` raising `CorpusError` when a YAML file parses to something other "
        "than a mapping (e.g. a bare list); `load_corpus` raising `CorpusError` when the given "
        "corpus directory does not exist. Use `tmp_path` fixtures to build minimal case directories "
        "by hand — no real corpus fixture, no network, no async. Commit the result on a NEW branch "
        "(never `main`), with a real commit message following this repository's own convention (see "
        "CLAUDE.md/AGENTS.md/CONSTITUTION.md for the convention this workspace actually uses — read "
        "them, do not guess). Do not push."
    ),
    "method": (
        "Read `eval/_capture/corpus.py` in full (176 lines) before writing anything — the four error "
        "paths named above are `_read_yaml`, `_load_inputs` is not one of them (it degrades to empty "
        "on missing files rather than raising), `load_case`, and `load_corpus`. Read one existing "
        "test file under `tests/eval_replay/` (e.g. `test_selftest_corpus.py`) for this repository's "
        "own pytest style and fixture conventions before adding a new test file — do not invent a "
        "new style. Place the new test file under `tests/eval_replay/` alongside the others unless "
        "an existing file there is the obviously correct home for it. Run `make check` yourself "
        "before proposing `done` if you can — the platform runs it again regardless as the actual "
        "gate."
    ),
    "assumptions": (
        "This is a real, standalone, already-scoped gap in this workspace's own backlog (bead "
        "a2web-2yd), narrowed here to one already-identified untested module rather than the whole "
        "harness — it is not attached to any other in-flight change. Acceptance: `corpus.py`'s four "
        "`CorpusError` guard clauses are each covered by at least one direct, deterministic, "
        "network-free unit test. If investigation shows a guard clause is unreachable or already "
        "covered somewhere not found here, say so precisely with the trace as evidence rather than "
        "manufacturing a redundant test. This repository is not yours to push; a local commit on a "
        "new branch is the complete, correct outcome."
    ),
}


def main() -> int:
    item_id = new_item_id()
    item_path = QUEUE / ITEMS / f"{item_id}.jsonl"
    append(
        item_path,
        backlog.ITEM,
        {"event": "created", "loop": "default", "frame": FRAME},
        actor="yf-24",
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
        # the-platform-delivers-the-workspace-commit: the a2web-luh attempt spent $2.5073 of the
        # original $5.00 allowance without reaching the gate; $2.4927 remains. This frame targets
        # a2web-qgo's $1.86 shape (small, one module, one test file) -- ceiling set at $2.00,
        # leaving margin inside what is left without inviting a second full turn.
        cost_ceiling_usd=2.00,
    )

    record = take_turn(
        places,
        executor,
        limits=limits,
        owner="yf-24",
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
