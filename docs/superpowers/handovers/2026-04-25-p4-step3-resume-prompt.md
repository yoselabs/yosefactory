# Resume Prompt — P4 Pipe-and-filter Dispatch (post step 3)

> **Paste this verbatim into a fresh session to pick up the work.** It assumes the new agent has no prior context.

---

## Where we are

Mid-flight on P4 — collapsing `pipeline/dispatch.py` to the vision §7.3 composition-root shape by extracting bounded contexts out of the fat `preflight.py`.

- **Spec**: `docs/superpowers/specs/2026-04-25-p4-pipe-and-filter-design.md` — 10 steps, 4 stages (A extract, B adopt, C collapse, D close). Step 8 is the load-bearing collapse; everything before it is additive.
- **Landed on `main`**: steps 1 → 3. `make check` green throughout.
- **Next**: step 4 — rename `PreflightOutcome` → `RunIntent` + move to `domain/run_intent.py`.

Recent commits:
```
486e05a P4 step 3 — extract gating checks into pipeline/gating.py
3eba280 P4 step 2 — move routing logic from preflight to ingress
928bf81 P4 step 1 — extract ingress.parse_event
```

P1, P2, P3 all Executed. Effect ADT + interpreter live; all four stage handlers are adapter-pure (execute → effects → interpreter). `StageOutcome.blocked` / `.error` replaced by `AwaitHumanDecision` + `MarkBlocked` effect arms scanned via `_pipeline_pause_reason`.

## Required reads before doing anything (in order)

1. `docs/superpowers/specs/2026-04-25-p4-pipe-and-filter-design.md` — live spec. Skim §Plan + §Non-goals.
2. `CLAUDE.md` at repo root — architecture rules (domain purity, pipeline as composition root).
3. `packages/engine/src/a2sdlc/pipeline/preflight.py` — the coordinator that still drives the flow; knowing what's left to extract from it clarifies step 4+ shape.
4. `packages/engine/src/a2sdlc/pipeline/ingress.py` + `gating.py` — the two new homes. Shape matters for step 5.
5. `docs/vision/02-architecture-vision.md` §7.3 — target composition-root shape that step 8 aims for.

## State to not re-discover

### Current pipeline/ layout (post step 3)

```
pipeline/
├── breakers.py        — review-cycles + cost-ceiling checks (unchanged)
├── context.py         — feedback assembly helpers (unchanged)
├── dispatch.py        — composition root, still ~240 LOC
├── effects_apply.py   — interpreter (P3)
├── feedback_routing.py — tiny routing helper
├── gating.py          — NEW (step 3): check_ticket_active + check_duplicate_run_id + re-exports
├── ingress.py         — NEW (steps 1+2): parse_event + resolve_routing
├── preflight.py       — thinner; still owns branch setup + intent building + breaker calls
├── stage_executor.py  — agent runner (unchanged)
├── merge_flow.py      — DELETED in P2
└── stage_run.py       — DELETED in P2
```

### Migration surface for step 4

`PreflightOutcome` is used as a type annotation in:

- `stages/spec.py`, `stages/implement.py`, `stages/review.py`, `stages/merge.py` — via `ctx.pre: PreflightOutcome | None`
- `stages/_shared.py` — helper signatures
- `pipeline/dispatch.py` — `DispatchContext.pre` field + signatures in `_run_attempted_stage`
- `pipeline/preflight.py` — the class definition itself
- `tests/**` — lots of test files import it

Step 4 per spec = rename + relocate. Options:
- **A**: keep `PreflightOutcome` as an alias for `RunIntent` during this step (minimal churn, alias dies at step 9).
- **B**: rename all call sites now; grep-and-replace.

Option A is safer for the intermediate commit. Spec says: "Keep a `PreflightOutcome` alias pointing at `RunIntent` for one step to avoid breaking contract tests; drop it in step 9."

### The per-run context fields on DispatchContext stay

Handlers still read `ctx.pre` to access the PreflightOutcome/RunIntent. Step 7 exposes `ctx.intent` as an alias (same object, different typed name); both work. Non-goal for P4: changing the handler signature to `execute(ctx, intent)` — intent lives *on* ctx.

### DispatchContext docstring reality

The fat context pattern is still present (`ctx.pre`, `ctx.comment`, `ctx.pr_lifecycle`, `ctx.pr_number`, `ctx.stage_config`, `ctx.run`). Step 6 introduces `RunContext` and aliases `DispatchContext` to it. Don't try to narrow in step 4 — it's a dedicated step.

### Tests that stress the flow

- `tests/pipeline/test_dispatch_e2e.py` — end-to-end safety net. If dispatch still works after each step, most refactors are OK.
- `tests/pipeline/test_dispatch.py` — targeted dispatch orchestration assertions.
- `tests/stages/test_*.py` — N6 standalone invocability tests (call `execute()` → `effects()` → `apply_effects()`). They assume populated ctx per-run fields — don't break that contract.
- Integration cassettes at `tests/integration/adapters/` — recorded GitHub traffic; unaffected by pipeline reshape but a regression safety net.

## Step 4 plan (the work you'll actually do)

1. **Create `domain/run_intent.py`** with a `RunIntent` dataclass. Fields identical to `PreflightOutcome`: `event`, `target_stage`, `clean_body`, `user_prompt_override`, `gates`, `self_answer`, `state_mgr`, `state`, `base`, `branch`.
2. **Add alias in `pipeline/preflight.py`**:
   ```python
   from a2sdlc.domain.run_intent import RunIntent
   PreflightOutcome = RunIntent  # alias — P4 step 4 transitional
   ```
   Then drop the original `@dataclass class PreflightOutcome` definition. `run_preflight` constructs a `RunIntent` instead.
3. **Update `PreflightResult = Union[RunIntent, DispatchResult]`** (signature stays semantically the same).
4. **L1 tests** in `tests/domain/test_run_intent.py` — minimal round-trip + field access.
5. **`make check` green** before committing.

Do not touch call sites that import `PreflightOutcome` — the alias keeps them working. Step 9 removes the alias once all call sites that read intent-shaped data use `RunIntent` directly.

## Steps 5–10 outline

- **5**: `dispatch.dispatch()` calls `ingress.parse_event` + `gating.check*` directly instead of (or alongside) `run_preflight`. `run_preflight` stays callable but becomes a thin composition.
- **6**: New `domain/run_context.py`. Alias `DispatchContext = RunContext` initially.
- **7**: `ctx.intent` exposed as alias for `ctx.pre` (same object, `RunIntent` typed).
- **8**: **Load-bearing collapse.** `pipeline/dispatch.py` ≤ 80 LOC composition root matching vision §7.3 target pseudocode. `_run_attempted_stage` shrinks too. Run full pytest + cassette tier before declaring done.
- **9**: Delete `pipeline/preflight.py`. Tests either adopt `ingress.resolve_routing` directly or call a shim.
- **10**: Spec status → Executed.

## Gotchas carried forward

1. **Pre-commit hook reformats then aborts.** If a commit silently doesn't land, re-stage (`git add -u <files>`) and retry. **Never `--no-verify`.**
2. **Effect list ordering matters** (P3 invariant). `MarkBlocked` before `CommentFinalize` so a failed comment doesn't leave the ticket "in progress."
3. **Solo-repo workflow**: no PRs. Commit + push directly to `main`.
4. **Cassette tier is live.** `make test-integration` replays 13 recorded tests. If P4 surfaces coupling to `adapters/review/*.py` or `adapters/work/*.py` response shapes (it shouldn't — P4 is orchestration-only), re-record per `CLAUDE.md` instructions.
5. **Don't rename modules this phase.** P7 owns `pipeline/` → final layout relocation. `ingress.py` and `gating.py` stay in `pipeline/` until P7.
6. **`PipelineEvent` stays the event shape.** Full Event ADT retrofit is post-V1.0. Pattern-matching over `event.is_closed`, `event.is_feedback`, `event.trigger_stage` is the V1.0 surface.
7. **`preconditions()` stays a no-op.** All four handlers return `None`. Step 4 does not move breakers into handler preconditions — P5 or later can.

## Verification

Before declaring a step done:
- `make check` green end-to-end
- New L1 tests for any new module entry points
- For step 8 specifically: also run `make test-integration` (cassette replay) and L6 smoke if time permits
- **Manually inspect** that dispatch behavior is preserved — no prior test should have gotten weaker; all existing dispatch tests stay green

Good luck. Steps 1–3's pattern is "extract pure function → update call site → commit." Step 4 is a rename with an alias bridge — equally safe. Step 8 is the one to be careful with; run the full pytest tier before pushing.
