## Context

See proposal.md - Why. Relevant current state, verified against disk rather than assumed:

- `Places` (protocol split: queue/ledger/queue_lock/workspace/workspace_lock) shipped in
  `add-cross-repo-workspace` (2026-08-16). `take_turn` reads it; nothing in `src/` collapses it back
  to one path except `Places.local`, which `runtime/loop.py::main`/`scheduled_main` still call
  exclusively — cross-repo has no CLI surface and `main`'s own docstring says that is deliberate
  ("cross-repo... left to a caller that imports `run_loop` directly").
- The container (`run-the-factory-in-a-container`, `run-the-loop-inside-the-container`) ships a
  `workspace_scoped` posture (`isolated=False, workspace_scoped=True`) that grants `bypassPermissions`
  inside the workspace, with the container's own mount topology as the actual "cannot reach outside"
  boundary (design.md D3 of that change). Model/effort are pinned by default
  (`pin-the-executor-and-close-the-push-grant`) — `claude.run`'s own `model`/`effort` parameters
  default to the pinned pair, so no new wiring is needed to get them recorded.
- `run-the-loop-inside-the-container`'s own receipt (D4) already pointed `Places.local` at `/app`
  directly — source and queue+workspace the same mount, for one bounded, watched run, explicitly
  because nothing else was editing that tree at the time. That D4 reasoning is reused here for the
  *queue* half; the *workspace* half is now a genuinely separate repository, which is the case the
  compose file's `/app` vs `/data/workspace` split was built for in the first place.
- `openspec/changes/archive/2026-08-16-add-take-turn-integration-receipt` is the only prior cross-repo
  `take_turn` run, against a throwaway fixture. It reached `Outcome.FAILED` both times — a real agent
  did real work and committed it, but could not name a legal completion event the platform accepted
  (the vocabulary gap it documented). That finding is a live risk here, not resolved by anything
  shipped since.

## Goals / Non-Goals

**Goals:**
- One real `take_turn` call, queue = yosefactory, workspace = the real `a2web` checkout, running
  inside the container, against a small already-acknowledged a2web task.
- A receipt that distinguishes *ran* from *reached done*, quoting the ledger row, the spend row, and
  a2web's own `git log` (or their absence, precisely stated) — not a self-report.
- A concrete demonstration that the container's blast radius is exactly {yosefactory, a2web}: an
  attempted read/write outside both, and what happened.

**Non-Goals:**
- Not building a general cross-repo CLI, a config file format for "which second repo," or anything
  reusable beyond this one run — see proposal.md Non-goals. If this run's shape turns out worth
  keeping, that is a separate change, proposed on the strength of this receipt.
- Not fixing the `add-take-turn-integration-receipt` vocabulary gap in advance. If it recurs, it is
  reported as confirmation of a known defect, not patched mid-run.
- Not deciding a2web's own openspec workflow on its behalf — the seeded item names the task and the
  file; a2web's own `CLAUDE.md`/`AGENTS.md`/`CONSTITUTION.md` govern how the agent works once inside
  its workspace, and those are read live by the run (`workspace_scoped` admits them), not restated
  here.

## Decisions

**D1 — The driver is a standalone script, not a test, not a `src/yosefactory` module.**
`add-take-turn-integration-receipt` used a pytest file because its workspace was a disposable
fixture recreated per test run. This run's workspace is `~/Workspaces/a2web` itself — a real
checkout with its own history — so it is driven once, by a script (`scripts/run_a2web_turn.py`),
not by a test that could be re-collected and re-run by `pytest -q` in CI or by a future `make check`.
No production module needs to import this script; it is a call site, like `runtime/loop.py::main`
already is, and lives in the same tier (a caller of `take_turn`, not part of the protocol).

**D2 — Queue = `/app` directly (D4's precedent), workspace = a new `/data/a2web` mount.**
Verified before deciding: `git status --short` in yosefactory is clean, and no other worker is
known to be live-editing this tree during this run (Article III's "assume another worker is
editing files you cannot see" is a default caution, not a substitute for the actual check — the
check is what D4 relies on and what this design states explicitly). Pointing `queue` at `/app`
avoids fabricating a throwaway `.dev-workspace` clone whose ledger commits would not be the real
repository D014 is scored from. `workspace` is a genuinely separate bind mount
(`~/Workspaces/a2web:/data/a2web`), which is exactly the source/workspace separation the compose
file's `D1` (mount race) already defends — here it defends the *real* case that pattern was built
for, not a synthetic one.

**D3 — `docker compose run` with an override, not an edit to `docker-compose.yml`'s default.**
Same posture as D4: the shipped compose file's default (`./.dev-workspace:/data/workspace`) stays
untouched for ordinary single-repo dev use. This run adds a second bind mount and a different
`command` via `docker compose run --rm -v ~/Workspaces/a2web:/data/a2web factory <script>` (or an
equivalent `docker run` against the already-built image) rather than committing a new permanent
service — the two-mount configuration is specific to this receipt, not a new default others inherit
silently.

**D4 — Publication and board wiring are absent by omission, not by a flag.** The driver script
never imports `board.adapter`/`board.inbox`, and constructs `Places` with
`publish_workspace=False, publish_queue=False` directly (not via `runtime.loop`'s `--publish` flag,
which this call path does not go through at all). There is no code path from this script to either
push or board ingestion — the constraint is structural for this run, not policy-gated.

**D5 — `test_command=("make", "check")`.** a2web's own gate (`lint ty test-cov arch`), read from its
`Makefile`, not yosefactory's `pytest -q` default. `verify.may_write_done` takes `test_command` as a
parameter for exactly this reason — a foreign workspace's own definition of passing, not ours.

**D6 — The seeded item.** One `created` event, appended directly to a fresh
`backlog/items/<id>.jsonl` in yosefactory's queue (the same primitive
`add-take-turn-integration-receipt`'s fixture setup used), naming: add `"hepsiburada.com"` to
`_JS_HEAVY_HOSTS_SEED` in `src/a2web/fetcher/comprehension/gate.py`, matching the existing pattern
(`trendyol.com`, `aliexpress.com` already present) and a2web's own filed follow-up (bead
`a2web-cid`, `flag-interaction-gated-sections/tasks.md` §7.5). `method` names the test file
(`tests/capabilities/quality_gate/test_gate.py`) so the agent knows where the matching assertion
belongs; `assumptions` states explicitly that the item is a real, standalone follow-up not attached
to any in-flight a2web change, and that the commit must land on a new branch, never `main`.

## Risks / Trade-offs

- **The `done` vocabulary gap may recur.** [Risk] the agent does the real work, commits it, and still
  cannot propose a legal `done` — repeating `add-take-turn-integration-receipt`'s finding.
  → [Mitigation] none attempted in this change (Non-goals). The receipt records exactly this if it
  happens: workspace git log vs. `TurnRecord.outcome`, read independently.
- **Two mounts is a real widening of the container's blast radius.** [Risk] the agent inside the
  workspace can read/write anything under `/data/a2web`, and anything under `/app` via the queue
  role, with `bypassPermissions`. → [Mitigation] this is the ruling this run exists to exercise, not
  a gap; the receipt's boundary demonstration (an attempted reach outside both mounts) is the check
  that the topology, not a policy, is what still holds.
- **`make check` inside a2web may be slow/expensive relative to the $5 budget.** [Risk] `test-cov`
  runs the full suite. → [Mitigation] `Guardrails.cost_ceiling_usd` and `wall_clock_seconds` bound
  the agent's own spend regardless; a slow gate costs wall clock, not extra model spend, since the
  gate itself is not billed to the executor.
- **A second real turn (retry) doubles spend.** [Risk] if the first attempt does not reach `done`,
  a second costs roughly the same again. → [Mitigation] the $5 allowance was set aside for exactly
  two live turns; a third is not attempted without reporting first.

## Migration Plan

Not applicable — no persistent config or schema changes. The two-mount container invocation is a
one-off command, not a new default. Rollback is: nothing to roll back (no `docker-compose.yml` edit
in the base case; see D3's override-not-edit).

## Open Questions

None — every unknown identified above either changes the task breakdown (and is answered by a
Decision) or is the thing the run itself measures (and is reported, not guessed at).

## Trail

- 2026-08-20 — **D7, added after Turn 1: `Dockerfile` gains `make`.** Not anticipated by any
  Decision above — every prior receipt used yosefactory's own `pytest -q` default `test_command`,
  so nothing before this run ever needed a foreign repository's own build tool on `PATH`. Found by
  a real crash (`VerificationError: 'make' is not on PATH`) inside `verify.may_write_done`, after
  the agent had already done real, correct work and committed it. Fixed narrowly — one package
  added to the existing `apt-get install` line — because it is infrastructure this run's own
  premise (run a foreign repo's real gate) requires, not a patch to make a measurement come out a
  particular way ([[D014]]'s prohibition is scoped to a breach response, not to completing wiring
  discovered incomplete on its first real use — the same shape as this container's own git-identity
  and non-root-uid fixes, both found the same way on their own first real runs).
- 2026-08-20 — **Turn 2's `failed` outcome is not a defect in this change's own wiring.** `may_write_
  done` ran for real, the agent proposed `done` correctly (contrast with `add-take-turn-integration-
  receipt`'s vocabulary-gap finding, which does not recur here), and the gate's rejection is fully
  accounted for by a2web's own test suite requiring browser-backend extras this container does not
  install — confirmed by a controlled host-vs-container comparison on the identical commit. Recorded
  as the honest stopping point rather than chased with a third live turn or an image change scoped
  to "install a foreign repo's browser stack," which the proposal's Non-goals already ruled out.
- 2026-08-20 — **`_dispose`'s `failed()` path does not close the item.** Observed, not designed
  around: when `may_write_done` rejects a `done` proposal, `_dispose` writes the turn's ledger record
  (`Outcome.FAILED`) but never appends an event to the backlog item itself — the item is left
  non-terminal (`doing`), same as it would be after any other `failed()` return. Both of this run's
  items were closed by hand (a `failed` event, actor `yf-19`, real reason) rather than left dangling.
  Whether this is the intended retry shape (an item left `doing` is presumably meant to be picked up
  by a fresh claim rather than closed) or a gap is not settled here — reported as an observation for
  write-back, not fixed.
