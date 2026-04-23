# Resume Prompt — P4 Pipe-and-filter Dispatch (post step 7)

> **Paste this verbatim into a fresh session to pick up the work.** It assumes the new agent has no prior context.

---

## Where we are

Mid-flight on P4 — collapsing `pipeline/dispatch.py` to the vision §7.3 composition-root shape. Stage A (extract) and stage B (adopt) are now fully landed on `main`.

- **Spec**: `docs/superpowers/specs/2026-04-25-p4-pipe-and-filter-design.md` — 10 steps, 4 stages (A extract, B adopt, C collapse, D close).
- **Landed on `main`**: steps 1 → 7. `make check` green throughout.
- **Next**: **step 8 — the load-bearing collapse.** dispatch.py ≤ 80 LOC, `_run_attempted_stage` ≤ 40 LOC.

Recent commits:
```
6f2686a P4 step 7 — expose ctx.intent alongside ctx.pre
b8a3b98 P4 step 6 — RunContext in domain/, DispatchContext alias
285b9d9 P4 step 5 — dispatch wires ingress + gating directly
6e13d06 P4 step 4 — rename PreflightOutcome to RunIntent in domain/
486e05a P4 step 3 — extract gating checks into pipeline/gating.py
3eba280 P4 step 2 — move routing logic from preflight to ingress
928bf81 P4 step 1 — extract ingress.parse_event
```

## Required reads before doing anything (in order)

1. `docs/superpowers/specs/2026-04-25-p4-pipe-and-filter-design.md` — live spec. Skim §Plan step 8 + §Rollout + §Backout.
2. `CLAUDE.md` at repo root — architecture rules (domain purity, pipeline as composition root, 500-line file cap, no PRs on solo repos).
3. `packages/engine/src/a2sdlc/pipeline/dispatch.py` — current state, **248 LOC**. This is what you're collapsing.
4. `packages/engine/src/a2sdlc/pipeline/ingress.py` (219 LOC) + `gating.py` (87 LOC) — the destinations for logic that doesn't survive the collapse.
5. `packages/engine/src/a2sdlc/domain/run_context.py` + `domain/run_intent.py` — the two new domain types. Note the `Any`-typed adapter handles (domain-purity trade-off — see Gotchas §8).
6. `docs/vision/02-architecture-vision.md` §7.3 — the target composition-root pseudocode. Step 8's success criterion is "dispatch reads like this."

## State to not re-discover

### Current pipeline/ layout (post step 7)

```
pipeline/
├── breakers.py         — review-cycles + cost-ceiling checks
├── context.py          — feedback assembly helpers
├── dispatch.py         — composition root, 248 LOC (step 8 targets ≤ 80)
├── effects_apply.py    — interpreter (P3)
├── feedback_routing.py — tiny routing helper
├── gating.py           — check_ticket_active + check_duplicate_run_id +
│                         check(ctx,event) aggregator + breaker re-exports
├── ingress.py          — parse_event + resolve_routing + resolve_intent
│                         (owns directives, routing, branch setup, state,
│                         idempotency, breakers, RunIntent build)
├── preflight.py        — thin composition shim (~58 LOC) — dies in step 9
└── stage_executor.py   — agent runner
```

### domain/ additions (live)

- `domain/run_intent.py` — `RunIntent` dataclass. `state_mgr` typed `Any` to preserve domain purity.
- `domain/run_context.py` — `RunContext` dataclass. All adapter handles (`work`, `git`, `review`, `runner`), lifecycle refs (`pr_lifecycle`, `comment`), evaluation refs (`telemetry`, `run`), observability (`progress_state`, `logger`, `config`) typed `Any`. This is a deliberate trade — see Gotcha §8.
- `RunContext` already carries both `pre: RunIntent | None` and `intent: RunIntent | None`. Step 7 populates both from dispatch pointing at the same object.

### Transitional aliases (live, die in step 9)

- `pipeline/preflight.py`: `PreflightOutcome = RunIntent` + `run_preflight(ctx)` shim.
- `pipeline/dispatch.py`: `DispatchContext = RunContext`.
- `RunContext.pre` and `RunContext.intent` both point at the same `RunIntent`.

### Current dispatch.py shape (the thing you're collapsing)

Top-level `dispatch()` is already the right shape — the pieces that need to shrink are `_ensure_draft_pr`, `_run_attempted_stage`, and `_outcome_to_dispatch_tuple`. `_run_attempted_stage` is currently ~57 LOC; spec target ≤ 40. `_outcome_to_dispatch_tuple` is ~45 LOC.

### Tests that stress the flow

- `tests/pipeline/test_dispatch_e2e.py` — end-to-end safety net. The load-bearing check for step 8.
- `tests/pipeline/test_dispatch.py` (≤ 500 LOC enforced by file-length lint) — targeted dispatch orchestration.
- `tests/pipeline/test_dispatch_closed.py` — ticket-closed early-return (split from test_dispatch.py in step 5 for file-length compliance).
- `tests/stages/test_*_stage.py` — N6 standalone invocability. Each calls `run_preflight(ctx)` to populate per-run state before invoking `execute()`. Preserve this contract — `run_preflight` must stay working until step 9.
- `tests/integration/adapters/` — cassette-backed GH replay. Unaffected by orchestration reshape; still a safety net. Run `make test-integration` after step 8.
- `tests/domain/test_run_intent.py` — L1 for RunIntent.

## Step 8 plan (the real work)

Goal: `pipeline/dispatch.py` reads like vision §7.3 pseudocode. ≤ 80 LOC. `_run_attempted_stage` ≤ 40 LOC.

Target shape:
```python
async def dispatch(ctx: RunContext) -> DispatchResult:
    parsed = ingress.parse_event(ctx)
    if isinstance(parsed, ingress.ParsedSkip):
        return DispatchResult(stage=StageName.SPEC, error=parsed.reason)
    event = parsed

    if event.is_closed:
        ctx.logger.info("dispatch.ticket_closed", extra={"key": event.key})
        ctx.work.mark_done(event.key)
        return DispatchResult(stage=StageName.MERGE, error="ticket_closed")

    if reason := gating.check(ctx, event):
        return DispatchResult(stage=StageName.SPEC, error=reason)

    intent = ingress.resolve_intent(ctx, event)
    if isinstance(intent, DispatchResult):
        return intent

    ctx.pre = ctx.intent = intent
    ctx.pr_number = _ensure_draft_pr(ctx, intent)
    ctx.stage_config = load_stage_config(intent.target_stage.value, ctx.config)
    _wire_comment_and_subscriber(ctx, intent)
    return await _run_attempted_stage(ctx, intent)
```

### What moves out of dispatch.py

1. **`_ensure_draft_pr`** — stays in dispatch (it's genuinely composition). But tighten: it currently takes `pr_lifecycle` as an explicit arg — pass it via `ctx.pr_lifecycle` that dispatch just set, or build the PRLifecycle inline (one line).

2. **Comment + subscriber wiring** — extract to a helper `_wire_comment_and_subscriber(ctx, intent)` returning nothing (mutates ctx). 4 lines of body.

3. **`_run_attempted_stage` internals** — extract the `(DispatchResult, success, error)` translator dance. Options:
   - Move `_outcome_to_dispatch_tuple` + `_pipeline_pause_reason` to a new `pipeline/stage_finish.py` module. Clean.
   - Or fold them into the stage handler's `effects()` return — bigger reshape, probably post-V1.0.
   - **Recommended:** move to `pipeline/stage_finish.py`. Keeps dispatch clean; the translator has its own test surface.

4. **Session-id construction** — 1 line, keep inline.

### Gates to pass

- `make check` green end-to-end.
- `make test-integration` green (13 cassette tests).
- If time: L6 smoke (`tests/test_cli_local.py` or similar — check the test tree).
- dispatch.py word count: `wc -l packages/engine/src/a2sdlc/pipeline/dispatch.py` ≤ 80 body LOC (docstrings + blank lines don't count — spec is about cognitive load, not strict line count).
- `_run_attempted_stage` body ≤ 40 LOC.

### Commit discipline

Step 8 is one commit. Do not split — the value is showing the collapse landed atomically. Pre-commit hook will run lint + format; if it reformats and aborts, re-stage and retry (no `--no-verify`).

## Steps 9–10 after step 8 lands

- **9**: Delete `pipeline/preflight.py`. Migrate the N6 standalone-invocability tests: each currently calls `run_preflight(ctx)` to populate per-run state. Replace with a helper `tests/fakes.py::populate_run_intent(ctx)` that calls `ingress.resolve_intent` directly (plus the ticket-closed/active short-circuits if needed). Remove `PreflightOutcome` + `DispatchContext` aliases. Remove `RunContext.pre` in favor of just `RunContext.intent`.
- **10**: Spec status → Executed. Update RFC cross-ref if needed.

## Gotchas carried forward

1. **Pre-commit hook reformats then aborts.** If a commit silently doesn't land, re-stage (`git add -u <files>`) and retry. **Never `--no-verify`.**
2. **Effect list ordering matters** (P3 invariant). `MarkBlocked` before `CommentFinalize` so a failed comment doesn't leave the ticket "in progress."
3. **Solo-repo workflow**: no PRs. Commit + push directly to `main`.
4. **Cassette tier is live.** `make test-integration` replays 13 recorded tests. If P4 surfaces coupling to `adapters/review/*.py` or `adapters/work/*.py` response shapes (it shouldn't — P4 is orchestration-only), re-record per `CLAUDE.md` instructions.
5. **Don't rename modules this phase.** P7 owns `pipeline/` → final layout relocation. `ingress.py` and `gating.py` stay in `pipeline/` until P7.
6. **`PipelineEvent` stays the event shape.** Full Event ADT retrofit is post-V1.0.
7. **`preconditions()` stays a no-op.** All four handlers return `None`. Step 8 does not move breakers into handler preconditions — P5 or later can.
8. **Domain purity vs. ambient context.** `RunContext` and `RunIntent` both type their adapter-layer refs as `Any` to satisfy the import-linter contract "domain imports nothing from other a2sdlc packages." This is a deliberate trade — `ty` tolerates it, but you lose attribute-level type-checking for `ctx.work.xxx()` calls inside dispatch/handlers. If you find yourself wanting to tighten, the right answer is Protocol types **defined in domain/** (not imported from adapters/) — but that's a separate refactor, not a step 8 concern.
9. **coverage-diff wants ≥ 95%.** After step 8, any previously-tested line that moved to a new location may show as "new uncovered" even though it's the same logic. Add focused L1 tests for extracted helpers (`stage_finish.py` in particular) rather than rely on e2e coverage.
10. **`test_dispatch.py` is at ~497 LOC — near the 500-line cap.** If step 8 pushes it over, move new tests to a topic-scoped sibling file (the precedent: `test_dispatch_closed.py` from step 5).

## Verification

Before declaring step 8 done:
- `make check` green end-to-end.
- `make test-integration` green.
- **Manually read dispatch.py** — it should read like the vision §7.3 pseudocode. If a reader has to jump to 3 helpers to understand control flow, split differently.
- **Grep for untouched dead code** — step 8 should delete the fat `_run_attempted_stage` arg list, not just rename it. If `pr_lifecycle`/`comment`/`pr_number`/`stage_config`/`session_id`/`telemetry` are still positional args after the collapse, you left complexity behind.

Good luck. The payoff step — after this lands, P4 is almost done (just delete-and-close left).
