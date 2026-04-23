# Resume Prompt — P2 Stage Handlers (post step 5)

> **Paste this verbatim into a fresh session to pick up the work.** It assumes the new agent has no prior context.

---

## Where we are

Mid-flight on P2 — promoting the four stage classes to full `StageHandler`s.

- **Spec**: `docs/superpowers/specs/2026-04-24-p2-stage-handlers-design.md` — 11 steps, 4 groups (A pure additions, B handler migration, C contract tests, D closure). **Step numbering is authoritative; each step's "Done when" reads as a Gherkin success signal.**
- **Landed on `main`**: steps 1 → 5. `make check` green.
- **Next**: step 6 — `ImplementStage` and `ReviewStage` become `StageHandler`s (same shape as SpecStage). REVIEW additionally emits `StageOutcome.inline_comments` and calls `post_inline_comments` when non-empty.

Recent commits:
```
6f3c35e P2 step 5 — SpecStage becomes a StageHandler
a002cdf P2 step 4 — ReviewAdapter.post_inline_comments + N9 diff-path guard
94ef6a3 Merge P2 step 1 — handler + outcome + session-storage shapes
```

## Required reads before doing anything (in order)

1. `docs/superpowers/specs/2026-04-24-p2-stage-handlers-design.md` — the live spec. Skim §Plan + §Security + §Rollout.
2. `CLAUDE.md` at repo root — architecture rules (domain purity, pipeline as composition root, etc.).
3. The current shape of `packages/engine/src/a2sdlc/stages/spec.py` — step 6 duplicates this pattern for IMPLEMENT + REVIEW.
4. The current shape of `packages/engine/src/a2sdlc/pipeline/dispatch.py::_outcome_to_dispatch_tuple` + the SPEC branch in `_run_attempted_stage` — step 6 will grow the branch for IMPLEMENT + REVIEW; step 9 collapses the whole thing.

## State to not re-discover

### DispatchContext is the transitional fat context (P2→P3)

`DispatchContext` now carries per-run orchestration state (`pre`, `pr_lifecycle`, `comment`, `pr_number`, `stage_config`, `run`). These are `None` before dispatch populates them in `dispatch()` right before `_run_attempted_stage`. Per `stages/handler.py` Protocol comment, this is deliberate transitional state — **P4 narrows it to `RunContext`. Do NOT introduce a narrower type now.**

Handlers read these off `ctx` via a small `_require` helper (`stages/spec.py` lines 283+). Copy that pattern for IMPLEMENT + REVIEW.

### StageOutcome shape

`domain/stage_outcome.py` now has `blocked: bool` + `error: str | None` alongside the existing `status`/`output_text`/`stats`/`merged`/`next_stage_hint`/`inline_comments`. These are P2 transitional; P3 replaces them with `MarkBlocked` / `CommentError` Effect variants.

### The dispatch branch shape for step 6

Today (`pipeline/dispatch.py::_run_attempted_stage`):
```python
if pre.target_stage == StageName.MERGE:
    ... execute_merge(...) ...
if pre.target_stage == StageName.SPEC:
    ctx.run = run
    outcome = await SpecStage().execute(ctx)
    result, success, error = _outcome_to_dispatch_tuple(pre, outcome)
    return result
# fall-through: IMPLEMENT, REVIEW → execute_ai_stage
```

Step 6 adds two more `if`s: IMPLEMENT → `ImplementStage().execute(ctx)`, REVIEW → `ReviewStage().execute(ctx)`. After step 6, `execute_ai_stage` has no callers and the fall-through is dead. Step 8 deletes `stage_run.py` entirely.

### Don't rename `pipeline/stage_executor.py`

The StageExecutor lives in `pipeline/` today and each handler imports it from there. P2 non-goals forbid renames. Step 7 (P7 really) owns the final layout.

## Step 6 plan (the work you'll actually do)

1. **ImplementStage.execute()** — duplicate `SpecStage.execute()` structure; the only SPEC-specific bit was the `self_answer` prefix (only SPEC sets `pre.self_answer`). IMPLEMENT has no special prompt prefix. Body is otherwise identical.
2. **ReviewStage.execute()** — same structure, two additions:
   - **PR context** injection on user_prompt: `user_prompt = f"{pre.clean_body}\n\n{pr_context}"` where `pr_context = ctx.pr_lifecycle.read_context(pr_number)`. Today this lives in `pipeline/stage_run.py` lines 71-76.
   - **post_review side effect** on success: `verdict = "APPROVE" if status == APPROVED else "REQUEST_CHANGES"; ctx.pr_lifecycle.post_review(pr_number, comment_body, verdict)`. Today this lives in `pipeline/stage_run.py` lines ~189-196.
3. **Inline comments (N1 wiring — the step-6 new thing)**: ReviewStage parses `inline_comments` out of the agent output and populates `StageOutcome.inline_comments`. Then it calls `ctx.review.post_inline_comments(pr_number, outcome.inline_comments)`.
   - Parser: see spec §step 7 — it's actually scheduled for step 7 (separate commit). For step 6, just thread `outcome.inline_comments` through; wire the parser in step 7.
4. **Dispatch branches** for IMPLEMENT + REVIEW (as described above).
5. **Empty out `pipeline/stage_run.py`** — `execute_ai_stage` has no callers after this step but **do NOT delete the file yet**; step 8 does that. Leave the function in place with a `# dead after P2 step 6` header comment OR actually delete it — spec says "will be deleted in step 8" so leave it.
   - Actually re-read the spec: "At this point `execute_ai_stage()` is down to its IMPLEMENT / REVIEW glue and will be deleted in step 8." — so after step 6, `execute_ai_stage` is still there but dead. Leave it.
6. **N6 contract tests** for both handlers — copy `tests/stages/test_spec_stage.py` structure. Two new files: `tests/stages/test_implement_stage.py`, `tests/stages/test_review_stage.py`.
7. **`make check` green** before committing.

## Gotchas carried forward

1. **Pre-commit hook reformats then aborts.** If a commit silently doesn't land, re-stage (`git add -u <files>`) and retry. **Never `--no-verify`.**
2. **SkipEvent is a 15-call-site `Exception` in `domain/exceptions.py`**; the Event-ADT variant is `SkipSignal`. Don't normalize by renaming in P2 — that's **P4**'s job.
3. **Solo-repo workflow**: no PRs. Commit + push directly to `main`. Feedback memory confirms this.
4. **Cassette tier is live now**. `make test-integration` runs 13 recorded tests (review + work adapters). If you touch `adapters/review/*.py` or `adapters/work/*.py` response-shape wise, re-record per §`CLAUDE.md` "GH adapter integration tier" instructions.
   - Recording needs a `ghs_` installation token for `iorlas/a2sdlc-smoke`. Previous session minted one via a one-shot `mint-installation-token.yml` workflow on the smoke repo (now deleted). If you need to re-record: recreate the workflow with `skip-token-revoke: true` + `actions/create-github-app-token@v3`, trigger it via `workflow_dispatch`, download the artifact, use the token, delete the workflow + artifact. Or minting instructions live in `docs/mode2/README.md`.
5. **Don't extend StageOutcome further in P2.** `blocked` + `error` are the P2 cap. Adding more fields signals scope creep; P3 reshapes this anyway.

## Verification

Before declaring step 6 done:
- `make check` green end-to-end
- `tests/stages/test_implement_stage.py` + `tests/stages/test_review_stage.py` pass with standalone-invocability semantics (N6)
- All existing `tests/pipeline/test_dispatch*.py` still pass (external dispatch behavior unchanged)
- **Manually inspect** `pipeline/dispatch.py::_run_attempted_stage` after the change — if all four `StageName` values now branch, the fall-through `execute_ai_stage` call is dead code. Dead code is OK in step 6 (step 8 deletes).

Good luck. Step 5's pattern is the template. Just don't get cute.
