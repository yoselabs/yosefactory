"""One-off driver: run `take_turn` for real, queue = this repo, workspace = a real a2web checkout.

Not a `src/yosefactory` module and not imported by anything — `openspec/changes/
run-a-turn-against-a2web` built this; `score-d014-against-a2web` and now
`score-d014-second-attempt` reuse it unchanged except for `FRAME` and the `actor`/`owner` strings,
each targeting a different, still-open a2web item (prior FRAMEs' items are already committed to
a2web, see `score-d014-against-a2web/design.md` D1 and this change's design.md D1/D2). Cross-repo
`take_turn` has no CLI surface by design (`runtime.loop.main`'s own docstring); this is the "caller
that imports `run_loop` [`take_turn`] directly" that docstring names.

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
        "Implement bead a2web-qgo: surface the fetched page's own primary image URL to `ask` "
        "callers. Today `_ASK_META_ALLOWLIST` in src/a2web/fetcher_response.py (around line 273) "
        "keeps only `og.description` from the parsed metadata dict passed to `_curate_ask_meta`; "
        "every image signal the metadata parser already produces (`og.image*`, `twitter.image`, "
        "`jsonld[0].image`, or similar keys — read what the parser actually emits, do not guess "
        "the key names) is dropped. Add the page's own primary image URL to what `ask` responses "
        "carry, choosing ONE grounded value with a sensible fallback order (og:image, then "
        "twitter:image, then JSON-LD Product.image, then a literal hero `<img src>` if the "
        "existing extraction pipeline already surfaces one) — never pattern-guess or invent a "
        "URL (ADR-0014, docs/adr/0014-grounded-urls-only-off-domain-flagged.md: every URL a2web "
        "emits must be traceable to the fetched page). Do not rank or pick a 'best' image across "
        "a set (ADR-0012, docs/adr/0012-shape-and-relay-never-manufacture-a-selection.md): if the "
        "page designates one primary image, relay that one; do not invent a selection criterion "
        "of your own. The bead's own text leans toward a generic (not product-page-only), "
        "always-on emission — treat that as the default unless investigation shows a concrete "
        "reason not to, and if you deviate, say why in the commit message. Add or extend a "
        "capability test asserting the image URL is surfaced when present on a fixture page and "
        "correctly absent when the page has none. Commit the result on a NEW branch (never "
        "`main`), with a real commit message following this repository's own convention (see "
        "CLAUDE.md/AGENTS.md/CONSTITUTION.md for the convention this workspace actually uses — "
        "read them, do not guess). Do not push."
    ),
    "method": (
        "Read src/a2web/fetcher_response.py in full around `_ASK_META_ALLOWLIST` and "
        "`_curate_ask_meta`, and both cited ADRs, before changing anything. Find where the "
        "metadata dict passed into `_curate_ask_meta` is actually produced (`parse_metadata` or "
        "equivalent) to see the real key names available — do not assume the docstring comment's "
        "key names are exact. Read the existing `ask`/fetcher_response capability tests for the "
        "shape a new assertion should follow — do not invent a new test style. Create and check "
        "out a new branch before committing. Run `make check` yourself before proposing `done` if "
        "you can — the platform runs it again regardless as the actual gate."
    ),
    "assumptions": (
        "This is a real, standalone feature already scoped in this workspace's own backlog (bead "
        "a2web-qgo) — it is not attached to any other in-flight change in this workspace. Its "
        "acceptance is: an `ask` response for a page with a page-designated primary image now "
        "carries that image's URL, grounded (never guessed), single-valued (never a ranked set), "
        "and covered by a capability test. This repository is not yours to push; a local commit "
        "on a new branch is the complete, correct outcome. If investigation shows the metadata "
        "parser genuinely produces no usable image signal for the fixtures available, say so "
        "precisely rather than inventing one — do not build a code change the investigation does "
        "not support."
    ),
}


def main() -> int:
    item_id = new_item_id()
    item_path = QUEUE / ITEMS / f"{item_id}.jsonl"
    append(
        item_path,
        backlog.ITEM,
        {"event": "created", "loop": "default", "frame": FRAME},
        actor="yf-23",
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
        # score-d014-second-attempt: $3.00 granted for this dispatch, two prior turns cost
        # $2.54/$2.39. Ceiling set at $2.80, leaving $0.20 margin -- not to be spent on a
        # second full turn without reporting back first.
        cost_ceiling_usd=2.80,
    )

    record = take_turn(
        places,
        executor,
        limits=limits,
        owner="yf-23",
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
