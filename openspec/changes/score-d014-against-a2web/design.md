## Context

Verified against disk, not assumed:

- `ship-a2web-toolchain-as-a-stopgap` (`1a19172`) baked `patchright`/`zendriver` into
  `yosefactory-factory:latest`. Its own receipt: `docker run … make check` inside the container on
  a2web `fd24220` → `1893 passed, 2 deselected, coverage 92.14%`, matching the host exactly.
  `run-a-turn-against-a2web`'s two failures (no `make` on `PATH`; missing browser backends) are both
  closed. Nothing else in the cross-repo path is known to have changed.
- `scripts/run_a2web_turn.py` (added by `run-a-turn-against-a2web`, `d2ad9f7`) is the only driver —
  cross-repo `take_turn` has no CLI surface by design (`runtime/loop.py::main`'s own docstring).
  It already: seeds a queue item, builds `Places` with `publish_workspace=False,
  publish_queue=False`, never imports `board.*`, uses `IsolationPolicy(isolated=False,
  workspace_scoped=True)`, and passes `test_command=("make", "check")`. Reused unchanged except for
  `FRAME` and `item_id`/owner bookkeeping — this change is not building new infrastructure
  (non-goal, same as the prior change).
- The hepsiburada item (`a2web-cid`) that the prior driver's `FRAME` targeted is **already done**:
  a2web's `fix-hepsiburada-js-heavy-host` branch, HEAD `fd24220`, carries the code change and a
  matching test. Re-running the same frame would either no-op against an already-clean tree or
  produce a duplicate/conflicting commit — exactly the make-work the dispatch warns against.
  Picking a different, still-open, small a2web backlog item is required for this run to be real.
- a2web's `bd ready` was read live (not assumed) to find a bounded item. `flag-interaction-gated-
  sections/tasks.md §7.4` names one already-acknowledged, already-scoped follow-up: `a2web-luh`,
  two emission sites, one capability test, an acceptance criterion already on the bead. Preferred
  over the larger/vaguer P2 items (typed missing-field reports, image-URL surfacing, `also_here`
  undercounting) precisely because those are open-ended investigations, not small self-contained
  units — the dispatch's own bar.

## Goals / Non-Goals

**Goals:**
- One `take_turn` call, queue = yosefactory (`/app`), workspace = the real a2web checkout
  (`/data/a2web`), inside the container, reaching a real outcome recorded in the ledger.
- A receipt distinguishing *ran* from *reached done*: `TurnRecord` JSON, the joined spend row,
  a2web's `git log` on the produced branch, proof of in-container execution
  (a grep count for the host's macOS user-home path prefix on the transcript → `0`), and a
  re-demonstrated container boundary.
- An honest statement of whether D014 is satisfied, from the ledger, per the 2026-08-17 ruling.

**Non-Goals:**
- Not building a general cross-repo CLI or config format — same as `run-a-turn-against-a2web`.
- Not fixing the missing `Yosefactory-Run` trailer on workspace commits unless it is cheap (D2
  below — it is not, and is reported open, not patched).
- Not deciding a2web's own OpenSpec/bd workflow on its behalf; `a2web-luh`'s acceptance criteria
  and its own `CLAUDE.md`/`AGENTS.md`/`CONSTITUTION.md` govern how the agent works once inside its
  workspace.
- Not merging or pushing a2web's `main`, or the run's own branch.

## Decisions

**D1 — Target `a2web-luh`, not the already-committed hepsiburada item.** Re-running an item whose
code and test already exist on disk (`fd24220`) is not a real run of the platform against new work
— either the tree is already clean (no-op, nothing for the ledger to show) or the agent redoes work
that exists, which is the trivial-commit-to-satisfy-a-criterion the dispatch names by name. `a2web-
luh` is real, open, small, and independently useful (ADR-0009's "never silently miss a URL" is the
whole point of a2web's design; a hint that silently loses its severity is exactly the defect that
principle exists to catch).

**D2 — The `Yosefactory-Run` trailer gap is reported, not fixed.** `turn.commit()` (`runtime/
turn.py`) composes both platform trailers via `git interpret-trailers`, but it is called only
against `places.queue` (three call sites: `declared`, `claim`, the terminal `commit()` at line
~797) — never against the workspace. The workspace commit is made by the executor itself, inside
its own sandboxed turn, following the `FRAME`'s prose instruction to "commit … with a real commit
message following this repository's own convention." There is no code path that injects a trailer
into that commit; fixing it means deciding **who commits the workspace's own work** — the §6.3
tension already on record in `run-a-turn-against-a2web`'s design.md and in [[D014]]'s 2026-08-17
trail, with two unbuilt options (the platform commits the workspace instead of the agent; a
`prepare-commit-msg` hook installed for the run). Both are architecture, not a line edit — deferred,
same as the prior two receipts, and reported as still open per the dispatch's instruction not to
claim provenance the artifact does not carry.

**D3 — Reuse the exact container/mount shape of the prior receipt.** `docker run` (or `compose run`
with an override), `--user 1000`, `-v ~/Workspaces/yosefactory:/app -v ~/Workspaces/a2web:/data/
a2web`, nothing else — the two-mount boundary the dispatch asks to be re-demonstrated, because the
image was rebuilt (browser stopgap) since the last proof.

**D4 — Board and push stay off by the driver's existing construction**, not by a new flag: `Places(
publish_workspace=False, publish_queue=False)`, no `board.*` import anywhere in `run_a2web_turn.py`
or its call path. Verified by reading the script (not assumed) before running it.

**D5 — `owner` and item id are fresh** (`yf-21` in place of `yf-19`), so the new ledger row and
backlog item are distinguishable from the prior run's without touching its history (D002).

## Risks / Trade-offs

- **`a2web-luh`'s scope may be larger than it reads.** [Risk] "verify the terminal path" could
  surface that escalation genuinely does not happen and requires a real code fix beyond the two
  named sites. → [Mitigation] the $2.50 per-turn ceiling and 45-minute wall clock bound the cost
  regardless; if the agent cannot reach a clean `done` within budget, that is reported precisely
  (Article VII / the dispatch's root-cause mandate), not patched or re-run silently.
- **A second live turn doubles spend against the $5 allowance.** → [Mitigation] budget two turns,
  as authorised; report exact spend either way.
- **The trailer gap means the produced commit cannot be machine-joined to its run from a2web's git
  log alone.** → [Mitigation] the ledger row is the authoritative join per the 2026-08-17 D014
  ruling; this design and the closing report both state the gap plainly rather than imply the
  commit carries provenance it does not.

## Migration Plan

Not applicable — no persistent config or schema change. The `FRAME` edit in `scripts/
run_a2web_turn.py` is committed as part of this change (queue-side, yosefactory's own file); nothing
in a2web is touched by this repo directly.

## Open Questions

None outstanding before running — the only real unknown (does `a2web-luh` reach `done` inside
budget) is what the run itself measures, not something to guess at here.

## Trail

- 2026-08-21 — **turn 1 found the `isolated`-field defect and stopped on its own budget.**
  `take_turn`'s `isolated` kwarg (default `True`) is decorative on this direct-call path — the
  real posture comes from the `IsolationPolicy` handed to the executor closure — and this driver
  never passed it, so the record contradicted the run (`cb2d2fa` fixed the equivalent gap in
  `run_loop`'s own call site; this one was missed). Fixed (D2's sibling, not D2 itself — one line,
  in scope). Separately, turn 1 hit its own $2.50 cost ceiling before committing
  (`failure_kind: budget_exhausted`), leaving real, on-target root-cause work uncommitted in
  a2web (`terminal.py`, `tier_walk.py` — tracing the general escalation classifier, not just the
  two literal `reddit.py` sites the frame named). Kept, not reset, for turn 2 — discarding correct
  work to hand the next turn an artificially clean slate would have been closer to shaping the
  measurement than observing it.
- 2026-08-21 — **turn 2: a2web's gate passed for real; the platform's own vocabulary refused the
  `done` write.** The agent built on turn 1's uncommitted diff, added a capability test, and
  committed `9e183e4` on a new branch (`fix-reddit-archive-rescue-escalation`) — real code,
  matching `a2web-luh`'s acceptance criterion, `make check` presumably green (the code path in
  `runtime/turn.py` only reaches the vocabulary-validating `append()` call *after*
  `verify.may_write_done`'s gate has already passed). The turn still ended `failed`: the `done`
  proposal omitted the required `effects` field (`backlog.VOCABULARY_SPEC`'s `done` rule requires
  `effects` and `verified_by`), and `append()`'s own fold validation refused it. **This is the
  vocabulary gap `add-take-turn-integration-receipt` first found and `run-a-turn-against-a2web`'s
  design.md named as a live, unresolved risk — it recurred, exactly as flagged, on the first run
  where an environment defect was no longer in the way to mask it.** Not patched: fixing it means
  changing `workflows/turn-skill.md`'s standing proposal instructions, which is platform-wide
  infrastructure outside this change's declared scope, and D014's own mandate forbids patching a
  gap discovered on the scored path. Reported as the honest stopping point instead of attempted a
  third time — the $5 allowance was budgeted for exactly two live turns ($4.9287 spent across
  both) and a third is not attempted without reporting first.
- 2026-08-21 — **the boundary-proof grep found a real caveat, not a leak.** `grep -c` for the
  host's user-home path prefix on turn 2's transcript read `1`, not `0` — traced to a stale,
  host-compiled `.pyc` cache under a2web's own bind-mounted tree whose bytecode retains its
  original compile-time `co_filename`, surfaced inside a captured pytest failure traceback. The
  separate `id`/`ls /Users`/`ls /data` boundary demonstration is unaffected by this and is the one
  that actually shows what the container itself can reach. Recorded because the check exists to
  catch exactly this class of thing, and a caveat found and explained is worth more than a check
  that happened to read clean.
