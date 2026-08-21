## Context

Verified against disk before writing anything below (Article XII):

- `openspec/changes/archive/2026-08-21-score-d014-against-a2web/design.md` and
  `openspec/changes/archive/2026-08-21-teach-the-done-event-schema/design.md` both read in full.
  The first diagnosed the `done`-refusal as environment-then-vocabulary; the second corrected it:
  the vocabulary *was* taught (`teach-event-vocabulary` wired `Invocation.vocabulary` at the one
  `turn.py` call site), the defect was distance-from-the-write on a long real turn, not absence.
- `decisions/D014-*.md` (unit, threshold, clock, void conditions, breach mandate — scored from the
  ledger per the 2026-08-17 ruling), `D022-*.md` (`take_turn` is the unit; platform may push,
  scoped, not exercised here), `D023-*.md` (environment stopgap — a2web's browser extras already
  baked into the image, dated 2026-08-21, same day as this dispatch — confirms `S989` is closed and
  the image needs no further change).
- `signals/S989-*.md` (environment gap, closed) and `S990-*.md` (instruction decay, the open
  question this run tests).
- The dispatch states today is 2026-08-21, one day later than the original dispatcher believed.
  Checked: system date is in fact 2026-08-21 (not 2026-08-20) — the correction is confirmed, not
  contradicted. Window (2026-08-24) still open, three days out.
- a2web state, read live rather than assumed: `fix-reddit-archive-rescue-escalation` at `9e183e4`,
  clean, holds `a2web-luh`'s real fix. `main` at `6f26e89`, untouched. `bd ready` lists 60 open
  items; `a2web-luh` and `a2web-1uh` both still show as open despite their fixes already existing
  on disk (`9e183e4` and a prior `SECURITY.md` respectively) — stale-open beads, not this change's
  job to close, noted so the next worker doesn't rediscover them as new findings.
- Candidate items read for boundedness before picking: `a2web-k5b` ("a handler that parses nothing
  reports success", arxiv listing regex rot) turned out to be **already fixed** — `git log` on
  `src/a2web/handlers/arxiv.py` shows `113579b feat(handlers): all nine handlers can report a dead
  parser, not just three`, and the current source already guards `parsed.is_rot` before returning
  `Verdict.ok`. A third stale-open bead, ruled out the same way as `a2web-luh`/`-cid`/`-1uh` before
  it, not picked. `a2web-qgo` (surface primary image URL) read in full: single call site
  (`_ASK_META_ALLOWLIST` in `fetcher_response.py`), governed by two already-decided ADRs (0012, no
  manufactured selection; 0014, grounded URLs only), no upstream code changes needed
  (`og.image`/`twitter.image`/JSON-LD image keys are already produced by the metadata parser this
  repo consumes, just not on the allowlist) — bounded the way `a2web-luh` was bounded in the prior
  change, and genuinely untouched (no commit on any branch touches `fetcher_response.py`'s image
  handling).

## Goals / Non-Goals

**Goals:**
- One `take_turn` call, queue = yosefactory (`/app`), workspace = a2web on a fresh `main`-rooted
  branch (`/data/a2web`), inside the container, reaching a real outcome in the ledger.
- A receipt distinguishing *ran* from *reached done*, matching the prior change's shape: `TurnRecord`
  JSON, the joined spend row, a2web `git log` on the produced branch, the container boundary
  re-demonstration, and a host-path grep with investigation rather than an assumed leak.
- The second, independent measurement this run produces: did the repositioned S990 reminder survive
  a real long turn, i.e. did the `done` proposal carry `effects` this time.
- An honest, ledger-sourced yes/no on whether D014 is satisfied.

**Non-Goals:**
- Not building new cross-repo infrastructure — `run_a2web_turn.py` is reused, only `FRAME` and
  actor/owner strings change, same as both prior changes.
- Not touching `verify.may_write_done`, `backlog.ITEM.rules`, or `VOCABULARY_SPEC` under any
  outcome — a fourth precise failure, root-caused, is an acceptable and useful result per the
  dispatch; patching the gate is the one thing explicitly forbidden regardless of outcome.
- Not fixing the `Yosefactory-Run` trailer gap on workspace commits (`teach-the-done-event-schema`
  design.md already stated the decision as open, architecture-sized, not this change's scope).
- Not closing the stale `a2web-luh`/`a2web-1uh`/`a2web-k5b` beads — a2web's own backlog hygiene,
  outside this repo's ownership.
- Not merging or pushing a2web's `main` or the run's own branch.

## Decisions

**D1 — Target `a2web-qgo`, a fresh item, from a fresh `main`-rooted branch.** Both items already
committed by the prior attempt (`a2web-luh`, `a2web-cid`) are explicitly ruled out by the dispatch.
Continuing directly from `fix-reddit-archive-rescue-escalation`'s tip was considered and rejected:
that branch's single commit is a finished, self-contained bugfix with its own acceptance criterion
already met — extending it would either be scope creep on a closed bead or would entangle two
unrelated beads' provenance on one branch, muddying the measurement this run exists to take. a2web
was checked out to clean `main` (`6f26e89`) on the host before the container run, so the agent's own
`git checkout -b` (per `FRAME`'s existing instruction) starts from the same root everyone else
starts from.

**D2 — `a2web-k5b` ruled out on read, recorded as a second stale-open bead found in passing.** The
dispatch's own precedent (`a2web-1uh`) was to note a stale bead without spending scope closing it.
Same treatment here.

**D3 — Reuse the exact container/mount shape of the prior two receipts.** `docker run --user 1000
-v ~/Workspaces/yosefactory:/app -v ~/Workspaces/a2web:/data/a2web`, nothing else — `docker compose`
is not used (its default service definition adds a third mount), demonstrated by showing the
compose config's extra mount and by running the plain `docker run` form instead.

**D4 — Board and push stay off by the driver's existing construction, re-verified by reading code
now rather than trusting the prior receipt.** `run_a2web_turn.py` constructs `Places(
publish_workspace=False, publish_queue=False)` and imports no `board` module; a full-text search of
`src/yosefactory/runtime/turn.py` and `runtime/loop.py` for `board`/`Board` returns nothing — there
is no board mechanism reachable from `take_turn` in this codebase at all, not merely a disabled one.

**D5 — `owner`/actor fresh** (`yf-23`, this worker's id), so the new ledger row and backlog item are
distinguishable from prior runs' without touching their history (D002).

**D6 — Cost ceiling $2.80**, against the $3.00 granted, leaving $0.20 margin. If the first turn
exhausts budget before reaching `done` or `failed`, that is reported and NOT retried without first
reporting to the director — the same discipline the prior change used for its two-turn budget,
scaled down for the smaller allowance here.

## Risks / Trade-offs

- **`a2web-qgo`'s own bead lists open design questions (scope: product-only vs generic; trigger:
  always vs conditional) rather than a fully closed acceptance criterion**, unlike `a2web-luh`'s.
  [Risk] the agent could stall deciding rather than building. → [Mitigation] the bead's own text
  states a leaning (generic emit, always-on) and both governing ADRs are already decided and cited
  in `FRAME`; the agent is instructed to make and record its own bounded call if genuinely
  ambiguous, not to treat the open questions as blocking, matching how `a2web-luh`'s FRAME handled
  its own residual ambiguity (terminal-path verification could have shown no fix was needed at
  all, and that was named a legitimate outcome in advance).
- **A single $2.80-ceilinged turn may not be enough to reach `done`** on a real feature (previous
  successful-gate turn cost $2.39 for a narrower two-site fix). → [Mitigation] this is itself
  useful signal about turn sizing under D014, reported plainly; no silent re-run.
- **The image URL feature touches ADR-governed territory (ADR-0012, ADR-0014)** — a wrong
  implementation could violate a product tenet. → [Mitigation] both ADRs are cited directly in
  `FRAME`, and a2web's own gate (`make check`) is the actual enforcement; this repo does not
  relax or bypass it regardless of outcome.

## Migration Plan

Not applicable — no persistent config or schema change. The `FRAME` edit in
`scripts/run_a2web_turn.py` is committed as part of this change (queue-side, yosefactory's own
file); nothing in a2web is touched by this repo directly.

## Open Questions

None outstanding before running — whether the S990 fix holds under real budget pressure, and
whether `a2web-qgo` reaches `done` inside $2.80, are exactly what the run itself measures.
