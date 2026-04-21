# Mode 2 Hardening — Follow-ups After 2026-04-21 Smoke

Written after 11 fixes landed + end-to-end verification on `iorlas/a2sdlc-smoke` ticket #10.
Priority shorthand: **P0** = blocks Phase 2 / data loss risk, **P1** = correctness
gap that will bite soon, **P2** = UX / polish.

## P0 — Correctness & architecture

### P0.1 · Mode 2 engine-level idempotency

**Problem.** `cli/dispatch.py` Mode 2 branch doesn't populate
`DispatchContext.run_id`. `StateManager.check_idempotency` returns early with
`False`. Result: every triggering event (label change, comment, re-delivery)
re-runs the whole stage, even if the previous run finished. The
GHA-level `concurrency:` group serializes but doesn't dedupe.

**Why it matters.**
- Phase 2 (Jira dispatcher) relies on webhook delivery, and Jira redelivers
  aggressively on 5xx. Without idempotency the engine would burn cost on
  every redelivery.
- Even in Mode 2 today, the engine re-ran stages during ticket #8 when the
  state machine thrashed. Was only masked by state corruption preventing
  progress.

**Fix sketch.**
- Derive run_id deterministically: `f"{event.key}:{target_stage.value}:{git_head_sha}"`.
- `target_stage` is known by line ~144 in `dispatch()` — set `ctx.run_id`
  there, then `check_idempotency(ctx.run_id)` already works.
- Write `stage_run_id` into state on success.
- Test with two rapid label cycles on the same issue — only the first should
  execute.

**Size.** ~60 LOC + one pipeline test. No new architecture.

---

### P0.2 · Reviewer identity for APPROVE verdict

**Problem.** The App that authors PRs can't submit APPROVE reviews on its
own PRs — GitHub returns 422 "Review Can not approve your own pull request".
`post_review` catches this and falls back to `create_issue_comment`, which
(a) posts a duplicate of the stage comment on the PR, and (b) means the PR
has 0 actual approvals, so branch-protection rules that require
approvals would block auto-merge.

**Current mitigation.** Smoke repo has no branch protection, so the
engine-side `check_human_approval` is bypassed under `gates.merge=AUTO`.
Works for smoke, would fail in any production repo with branch protection.

**Options (ranked by ROI).**
- **(c) Skip PR review API in Mode 2 entirely.** Engine verdict lives in
  the stage comment on the issue; transition stage:review → stage:merge
  directly based on it. Zero new secrets, works for Phase 2 (Jira has no
  PR-review concept), loses the GitHub-native approval artifact (but you
  get that from the PR being green + the engine's comment).
- **(b) Dedicated service-account PAT.** Second secret in each consumer
  repo, narrowly scoped to PR-review. Branch protection sees a real
  approval. Heaviest setup.
- **(a) Second reviewer App.** Cleanest auth model, but doubles the app
  installation burden per consumer repo.

**Recommendation.** Start with (c) as a config flag — it unblocks Phase 2
immediately and can coexist with (b) later for repos with branch
protection. Add `review.post_to_github: bool` to config (default True);
skip the API call when False.

**Size.** ~30 LOC + test for the config switch.

---

### P0.3 · State storage: race conditions on concurrent MERGE

**Problem.** Current design:
- Per-ticket state.json lives on the ticket branch.
- `cleanup_base` (post-merge) checks out base, removes the runtime file,
  pushes.

**Races that break this.**
1. **Two tickets merging concurrently** → both call `cleanup_base`. One
   pushes first; the second's push rejects with non-fast-forward. We catch
   the exception and log a warning, but main ends up with the second
   ticket's state.json until the next cleanup-capable merge.
2. **Parallel A/B prompt runs on the same ticket** (documented use case per
   `feedback_parallel_runs` memory) would share the same branch and fight
   over state.json writes.

**Cleaner designs (in order of effort).**
- **Short-term, bounded:** detect rejection in `cleanup_base`, retry once
  with `git pull --rebase`. One retry handles the typical race.
- **Medium-term:** move state to a dedicated orphan branch
  `a2sdlc/state/{ticket_key}`. Never merged, doesn't pollute main, survives
  branch-delete. Git knows it; GitHub doesn't surface it on PR list.
- **Long-term:** state in `refs/notes/a2sdlc`. Proper separation of code
  history from pipeline bookkeeping. Requires explicit note fetch/push in
  each stage. Clean but adds one new git concept to the engine.

**Recommendation.** Short-term retry-with-rebase first (~10 LOC). Orphan
branch when Phase 2 / Jira arrives — because Jira has no "base branch"
concept at all, and the engine will need a tracker-agnostic state store
anyway.

---

### P0.4 · Label ≡ state.json coherence problem

**Problem.** Two sources of truth:
- `stage:*` label on the issue (readable by humans, triggers workflows).
- `state.json` on branch (read by engine, includes pr_number/cycles/cost).

They can disagree:
- Engine writes state → pushes → sets label → failure between these leaves
  state ahead of label or vice-versa.
- Human cycles a label → engine re-runs stage → state may not advance if
  early-return path is hit.
- PR-#7-leak bug (ticket #8) was caused by the two disagreeing — label said
  stage:merge, state said pr_number=7 from another ticket.

**Already listed as a TODO** ("State.json as authoritative") but deserves a
sharper framing now:

**Three clean options.**
- **(X) Label-as-source-of-truth, state as cache.** Engine reads label,
  consults state only for accumulated stats. On mismatch, label wins.
  Simplest. Loses pr_number/review_cycles durability on label-only pushes.
- **(Y) State-as-source-of-truth, label as display.** Engine reads state,
  writes label as a best-effort mirror. Label drift is cosmetic. Requires
  reliable state storage (see P0.3).
- **(Z) Single-source: stage + pr_number packed into the label.** e.g.
  `stage:merge:pr-42`. Ugly but eliminates the split. Requires label
  rewrites for pr_number updates — GH labels are slow.

**Recommendation.** Pair with P0.3: if we move state off branches to orphan
ref / notes, then state becomes durable and (Y) is clearly right. Deferring
this decision until P0.3 lands.

---

### P0.5 · Error UX — tracebacks in CI instead of actionable comments

**Problem.** MERGE failure on ticket #10 produced:
```
Process completed with exit code 1.
<full Python traceback, 80+ lines>
Dispatch blocked: Pull Request is still a draft
```

The engine's own "Dispatch blocked: ..." message is correct but buried.
The issue has no comment about the failure. Human must open the Actions
tab to see what broke — slow feedback loop for consumers.

**Fix sketch.** `cli/dispatch.py` should wrap `asyncio.run(dispatch(ctx))`
in a try/except that:
- Catches `GithubException` / `BlockedError` / `GitCommandError`.
- Posts a structured `🚨 Stage failed: <short reason>` comment on the issue
  (via the current work adapter).
- Logs the full traceback at DEBUG (still in CI artifacts) but doesn't
  include it in the issue comment.
- Sets `stage:blocked` label so humans have an obvious signal.

**Size.** ~40 LOC. Overlaps with existing `set_blocked` path — just extend it.

---

## P1 — Correctness gaps

### P1.1 · Engine-side token sniff

**Problem.** If `GITHUB_TOKEN` starts with `ghs_` (the GHA default token),
the engine can parse events but can't fire downstream `labeled` events —
label writes don't trigger workflow re-entries. State machine stalls
silently.

**Fix.** In `cli/dispatch.py`, read env.GITHUB_TOKEN; if it starts with
`ghs_`, raise `typer.Exit` with a one-line actionable message pointing
consumers to the GitHub App setup. The workflow preflight already hard-
fails on this, but engine-side defense-in-depth prevents local
misconfiguration from silently breaking.

**Size.** ~10 LOC.

---

### P1.2 · `issues:closed` action doesn't trigger engine cleanup

**Problem.** When a human closes the issue manually (or when it closes via
a PR merge that bypassed the engine), stale `stage:*` labels linger.
`is_ticket_active` catches new events → skip, but the label cruft on the
board misleads humans.

**Fix.** Handle `issues:closed` in `_parse_issues_event`: return a special
event type, and dispatch short-circuits to `set_done_label` → strip
`stage:*`. No AI call, no branch work.

**Size.** ~20 LOC + parse-event test.

---

### P1.3 · Duplicate PR comment on APPROVE self-review

**Problem.** `post_review` catches the 422 and posts `create_issue_comment`
on the PR with the full review body. The stage-completion comment on the
ISSUE already has the same body. Two sources of the same text clutter the
PR timeline.

**Fix.** Related to P0.2 — when we move to option (c) (skip PR review API
entirely), this goes away. Until then, just don't post the fallback
comment; the engine's issue-side comment is enough.

**Size.** Trivial — delete 2 lines in the except block.

---

### P1.4 · `gates: {merge: auto}` is undocumented for consumers

**Problem.** Default `GateConfig.merge = HUMAN`. Smoke repo needed
manual `gates: {merge: auto}` in `.a2sdlc/config.yaml` for end-to-end
automation. There's no docs page telling consumers this, nor the
trade-off (AUTO skips branch-protection human approval checks — fine for
trusted internal repos, scary for open source).

**Fix.** Add a Mode 2 onboarding doc covering:
- config.yaml required fields
- gate mode trade-offs (HUMAN for production, AUTO for trusted-internal)
- required secrets (A2SDLC_APP_ID, A2SDLC_APP_PRIVATE_KEY, CLAUDE_CODE_OAUTH_TOKEN, MLFLOW_*)
- the App installation + permission list
- a minimum-viable `a2sdlc-run.yml` consumer workflow

**Size.** ~1 page of docs. Could be auto-generated from the config model.

---

## P2 — UX polish

### P2.1 · "Agent" row in tool timeline has empty target column

Observed in ticket #2/#8/#10 live comments. Subagent dispatches appear as
`| 3:18 | Agent |  |` — the target column is blank. Could show the
subagent's declared purpose (first word of its prompt, e.g. "review",
"research").

### P2.2 · Stage comments don't link to the PR

Issue comments say "✅ Merged" but don't link to the PR that merged.
Humans must scroll up to find the PR number. Similarly, PR lacks a
back-link to the originating issue beyond `Closes #N` in the body.

### P2.3 · `needs-input` / clarification label management

When SPEC returns `QUESTIONS` status, `next_stage` returns None and the
pipeline halts. But no label or comment tells humans what's expected.
Should set a `needs-input` label + post the questions as a bulleted
comment so humans know how to unblock.

### P2.4 · MLflow session_id collision on parallel A/B runs

Already in TODO.md / `feedback_parallel_runs` memory. Derive
`session_id = f"{ticket_key}:{run_id}"` so parallel prompt A/B runs on the
same ticket don't share MLflow parent runs.

### P2.5 · Circuit breaker for runaway cost per ticket

No hard ceiling on accumulated spend per ticket. The existing review-cycle
circuit breaker only catches loops in REVIEW stage. An implementation
that keeps asking follow-up questions in SPEC could burn unbounded cost.
Add `max_cost_usd_per_ticket` config (default $10? $25?); if
`state.accumulated_cost_usd` exceeds, block stage with a clear comment.

---

## Ship-critical for Phase 2 (Jira dispatcher)

Before flipping the switch to Jira + real tickets:

1. **P0.1 (idempotency)** — hard requirement; webhook redelivery is
   guaranteed to happen.
2. **P0.2 option (c)** — Jira has no PR-review API at all; reuse the
   "engine verdict = decision" path.
3. **P0.3 (state storage)** — either the rebase-retry band-aid or the
   orphan branch. No "base branch" concept in Jira means state on branch
   tied to git is already half-wrong for the Jira world.
4. **P1.1 (token sniff)** — Jira dispatcher mode still uses GitHub for
   PR lifecycle; same failure mode applies.
5. **P0.5 (error UX)** — Jira tickets shouldn't silently stall. Post a
   comment + set a status on every engine failure.

Everything else is polish that can land post-Phase-2.

## Scenarios not yet tested

- **Concurrent tickets.** Two `agent`-labeled issues submitted within
  seconds. Today's `concurrency:` group is per-issue — two different
  issues run in parallel. State writes race? cleanup_base races?
- **Feedback loop.** Human posts a comment on the PR requesting changes.
  Engine should route to IMPLEMENT stage with the feedback. We wired this
  up but haven't exercised it.
- **Circuit breaker firing.** Force REVIEW → IMPLEMENT → REVIEW ≥ max_cycles
  to confirm the breaker triggers and blocks cleanly.
- **Mid-stage runner death.** Kill the runner mid-implement; confirm the
  next run picks up correctly. Depends on P0.1 landing first.
- **Ambiguous spec.** Ticket with deliberately vague acceptance criteria —
  does SPEC ask questions? Does it halt with `needs-input` UX (P2.3)?
- **Stage override via directive.** `base: develop` / `gate_spec: human`
  in the ticket body — need a smoke to confirm directives actually wire
  through.

## Items to prune from the live TODO

These TODO.md entries are done and can be removed:

- Entire "Logging" section (fixed in 56cf481).
- "Mode 2 auth/trigger follow-ups → `agent` label lingers" (fixed in
  3f046ca).
- "Mode 2 auth/trigger follow-ups → Existing-PR reuse" (fixed in 3f046ca).
