# a2sdlc Smoke Test Plan

Scenarios that can't be covered by unit tests — they require a real
GitHub App, the Claude Agent SDK, and the superpowers plugin on a live
runner. Run these after any change to dispatch, runner, adapters, or
the stage prompts. Keep this file honest: every scenario you actually
run gets a status row update; every scenario you add should have a
pass criterion that's concretely verifiable from `gh` / the repo, not
from the agent's self-report.

## Where this runs

- Engine repo: `yoselabs/a2sdlc`, branch `main`.
- Smoke repo: `iorlas/a2sdlc-smoke`, workflow pinned `@main`.
- Secrets: `A2SDLC_APP_ID` + `A2SDLC_APP_PRIVATE_KEY` + `CLAUDE_CODE_OAUTH_TOKEN` set on the smoke repo.
- Smoke config (`.a2sdlc/config.yaml`): `gates: {merge: auto}`, no `self_answer` (defaults to false).

## Pass criteria vocabulary

- **Post-merge clean** — issue closed, labels `[]`, PR merged with descriptive title (not `agent/N`), main's `.a2sdlc/` contains only `config.yaml`, `agent/{N}~1` has `state.json` for debug history.
- **QUESTIONS clean** — issue OPEN, labels include `needs-input`, final comment ends with `{"status": "questions"}` + load-bearing choices listed, PR is seed-draft only (no spec committed).
- **Breaker clean** — issue OPEN, `stage:blocked` label, "Blocked: `<reason>`" comment pinned.

---

## 1. Happy path — full pipeline

**What it validates:** dispatch composition root, preflight → ensure draft PR → SPEC → IMPLEMENT → REVIEW → MERGE transitions, title-promote-at-merge, pre-merge strip, progress telemetry, MLflow session wiring.

**Ticket shape:** clear scope, unambiguous deliverable. Good templates:
- "Add a short helper for X in `scripts/foo.py` — one function, one test."
- "Add a cross-reference helper to `docs/util.md` — one paragraph + worked example."

**Expected:** Post-merge clean. Cost $0.20–$4 depending on scope. Duration 2–15 min.

**Sentinel runs:**
- 2026-04-22 smoke #20 — $0.18 / 2 min, plugin loading was dormant (thin SPEC path).
- 2026-04-22 smoke #22 — $2.99 / 18 min, plugin loading active, full brainstorm + plan + TDD workflow ran.
- 2026-04-22 smoke #30 — ~14 min, validates cross-scope App token install (commit `1f401e1`, `x-access-token:${ENGINE_TOKEN}@github.com/yoselabs/a2sdlc` auth path). Install step worked while engine repo still public (over-specification harmless); private-repo path now unblocked.
- 2026-04-22 smoke #32 — ~5 min, validates **engine-repo-PRIVATE + workflow-inlined-in-smoke + cross-scope App token**. The reusable-workflow path (`uses: yoselabs/a2sdlc/.github/workflows/run-native.yml@main`) broke the instant engine went private — GitHub can't fetch reusable workflow files from a private cross-account repo on non-Enterprise plans. Fix: inline `run-native.yml` content into `iorlas/a2sdlc-smoke/.github/workflows/a2sdlc-run.yml`. Engine CODE still pulled authenticated via cross-scope token. PR #33 merged clean.

**Retry after:** any change to `pipeline/dispatch.py`, `preflight.py`, `stage_run.py`, `merge_flow.py`, `stages/*`, `adapters/work/github.py`, `adapters/review/github.py`, stage prompts.

---

## 2. QUESTIONS — Phase 1: agent pauses on load-bearing ambiguity

**What it validates:** SPEC decision-gate prompt + `mark_needs_input` label path + engine does NOT proceed to IMPLEMENT when agent returns `{"status": "questions"}`.

**Ticket shape:** multiple load-bearing choices with no reasonable default. Good templates:
- "Add metrics collection to the CLI." (which metrics? where stored? opt-out? schema?)
- "Add authentication to $SCRIPT." (scheme? storage? scope?)
- "Integrate with $EXTERNAL_SERVICE." (creds? format? retry?)

**Bad templates (don't use):**
- "Fix the CLI." — the agent will pick something reasonable and proceed.
- Anything with a single missing fact — the agent may infer.

**Expected:** QUESTIONS clean. SPEC terminates <3 min. Cost $0.15–$0.50.

**Sentinel runs:**
- 2026-04-22 smoke #24 — failed (went to IMPLEMENT despite `self_answer: false`); fixed by commit `2bf212f` (SPEC decision gate).
- 2026-04-22 smoke #26 (Phase 1) — ✅ $0.20 / 2:51, 4 questions listed, `needs-input` label present.
- 2026-04-22 smoke #28 (Phase 1) — ✅ with `### ❔ a2sdlc:spec` header (commit `af00029` icon live-sighted). 4:10 / ~$0.30, agent asked one focused follow-up before committing to design.

**Retry after:** any change to `prompts/stages/spec.md`, `_DEFAULT_TOOLS` in `stages/spec.py`, `mark_needs_input`, feedback routing.

---

## 3. QUESTIONS — Phase 2: resume on human answer

**What it validates:** `collect_issue_feedback` picks up `@a2sdlc` comment, dispatch routes as feedback event, SPEC re-enters with user_prompt_override, eventually produces a spec + proceeds to IMPLEMENT.

**Prereq:** a ticket sitting in Phase-1 state (open, `needs-input` label).

**Steps:**
1. Post a comment on the issue: `@a2sdlc <answers>`. Example answers to smoke #26's questions: `1) now CLI, 2) local JSONL file, 3) NOW_NO_TELEMETRY env var, 4) event-level only, no install ID`.
2. Wait for the `issue_comment` workflow run to fire.
3. Expect SPEC to re-enter. Two valid outcomes:
   - Agent has all info → writes spec + plan, returns `complete`. Proceeds to IMPLEMENT, etc.
   - Agent has partial info → returns `questions` again with remaining gaps. Loop back to Phase 2.
4. Validate that `needs-input` is stripped on the next stage transition (via `_strip_transient_labels`).

**Expected multi-turn:** up to 2–3 Q&A cycles on a deliberately-ambiguous ticket, then full pipeline to merge. Cumulative cost $2–$8.

**Sentinel runs:**
- 2026-04-22 smoke #26 (Phase 2, resume) — ✅ after user-authored `@a2sdlc` answer comment: SPEC re-entered with feedback as user_prompt_override, wrote spec + plan, IMPLEMENT ran full TDD cycle (red test commit → impl → hermetic fix), REVIEW approved first try (0 cycles), MERGE clean. **Cumulative cost $3.71, duration ~23 min, 1 Q&A round** (agent had enough info from round 1 answers; didn't ask follow-ups). PR #27 merged with engine-promoted title, labels empty, main clean. Icon logic not live-exercised (no post-change QUESTIONS finalize); covered by unit tests.

**Retry after:** any change to `feedback_routing.py`, `_parse_issue_comment_event`, `_strip_transient_labels`, `collect_issue_feedback`.

---

## 4. Feedback loop — human PR review on a merged-path ticket

**What it validates:** `collect_pr_feedback` picks up human review comment requesting changes, engine routes to IMPLEMENT with feedback, subsequent REVIEW stage approves.

**Prereq:** a ticket where SPEC + IMPLEMENT have landed and a PR is in REVIEW (gate=human) or just-landed REVIEW.

**Ticket shape (preferred — label form, since 2026-04-28 / e993c13):** add the `gate:merge:human` label alongside `agent`. The engine re-reads labels fresh each dispatch (`ingress.resolve_intent`), so labels can be added/removed mid-pipeline and they win over body directives on conflict. Bracket form (`[a2sdlc gate:merge=human]`) still works as a fallback when no matching label exists — useful when you also need `base=` or `model=` overrides on the same ticket. The four `gate:*` labels (`gate:merge:human`, `gate:merge:auto`, `gate:spec:human`, `gate:spec:auto`) currently must exist on the repo (pre-created on `iorlas/a2sdlc-smoke` 2026-04-28); auto-create on first dispatch is open follow-up.

**Steps:**
1. On the PR, submit a review with `CHANGES_REQUESTED` and a specific feedback comment.
2. Expect engine to fire `pull_request_review` workflow, route to IMPLEMENT.
3. Verify review_cycles counter increments (visible in `state.json`).
4. IMPLEMENT addresses the feedback, REVIEW re-approves, MERGE happens.

**Expected:** Post-merge clean with `review_cycles >= 1` in the pre-strip `state.json`.

**Sentinel runs:**
- 2026-04-23 smoke #34 — ❌ first attempt: `gate_merge: human` directive was written in obsolete YAML form, parser silently ignored it, PR auto-merged on REVIEW approval. Wasted ~$1.50. Root cause: test_plan directive-syntax drift (fixed in the same session).
- 2026-04-23 smoke #36 — ✅ retry with correct `[a2sdlc gate:merge=human]` bracket syntax. `dispatch.transition from=review status=approved to=null` — gate honored. CHANGES_REQUESTED → IMPLEMENT routing worked (the primary scenario-4 mechanic); IMPLEMENT addressed the feedback within ~1 min; REVIEW re-approved at cycle 2. Found and fixed two bugs in the same session (0127e27, 28d9a6c).
- 2026-04-23 smoke #40 — ✅ revalidation after the two fixes shipped. Minimal ticket (one file), REVIEW paused on `gate:merge=human`, human APPROVE fired `pull_request_review` → `dispatch.start stage=merge` (not implement, the old bug path) → `dispatch.merged pr=41` 37s later. Merged by `app/a2sdlc`, not the human reviewer. Full "human approves, AI merges" UX confirmed end-to-end.

**Retry after:** feedback routing changes, review adapter changes, circuit-breaker-cycle logic.

---

## 5. Circuit breakers

### 5a. Review cycle breaker

**What it validates:** `check_review_cycles` trips when `review_cycles >= max_review_cycles`, stage is blocked before execution.

**Setup:** Force IMPLEMENT → REVIEW → CHANGES_REQUESTED → IMPLEMENT loop by setting `max_review_cycles: 1` in smoke config and asking for a ticket the agent will get "wrong" on first try, then human requests changes.

**Expected:** After the second REVIEW, next dispatch trips breaker: `stage:blocked` label + comment "Blocked: review cycle ceiling (X >= Y)."

### 5b. Cost ceiling breaker

**What it validates:** `check_cost_ceiling` trips when accumulated cost >= `max_cost_usd_per_ticket`.

**Setup:** Set `max_cost_usd_per_ticket: 0.5` in smoke config, file any non-trivial ticket.

**Expected:** After first SPEC stage, cumulative cost exceeds ceiling → next dispatch trips breaker.

**Sentinel runs:**
- 2026-04-22 smoke #28 (5b cost-ceiling) — ✅ breaker tripped at IMPLEMENT dispatch after resume SPEC pushed accumulated cost to $1.32 (ceiling $0.50). `stage:blocked` label added, `Blocked: Cost ceiling: $1.32 >= $0.50 per-ticket max` comment posted. Known minor artifacts: (1) duplicate "Blocked:" comment from the CLI error-handler path alongside the breaker's own, (2) workflow exit code `failure` instead of `success` on breaker trip — both UX-only, not regressions. Worth a follow-up cleanup but don't block validation.

**Retry after:** `pipeline/breakers.py` changes, cost-accounting changes in `stage_run.py` state write.

---

## 6. Stage override directives

**What it validates:** directive merging — labels for the common gate controls, brackets for free-text overrides (`base=`, `model=`) — both override project config; labels win on conflict.

**Ticket shape (preferred — label form for gates, brackets for `base`):** apply the `gate:merge:human` label alongside `agent`, and put any free-text overrides in body directives:
```
[a2sdlc base=develop]

<normal ticket body>
```

Equivalent (legacy) bracket-only shape — still parsed as a fallback when the matching label is absent:
```
[a2sdlc base=develop]
[a2sdlc gate:merge=human]

<normal ticket body>
```

(Not YAML front-matter. Earlier drafts of this plan and inline ticket templates used `gate_merge: human` under a `---` separator — that never parsed; the first run of scenario 4 auto-merged because the directive was silently ignored.)

**Expected:** Branch is `agent/{N}` against `develop` (not `main`). MERGE stage blocks on human approval even though project config has `gates: {merge: auto}`.

**Sentinel runs:**
- 2026-04-23 smoke #38 — ✅ PR #39 opened with **base=develop** (directive honored — `dispatch.branch_setup branch=agent/38 base=develop` visible from SPEC through REVIEW). REVIEW approved with `to:null` per `gate:merge=human`. No auto-merge — I completed the scenario with a manual squash-merge to develop at 13:52:25Z. Both directive mechanics validated in one run.

**Retry after:** `domain/directives.py` changes, `preflight.py` gate merging logic.

---

## 7. Closed-ticket short-circuit

**What it validates:** `is_closed` event triggers `mark_done` without invoking the agent, leaving no stage label behind.

**Setup:** Close any open agent-labeled issue manually via GitHub UI.

**Expected:** Engine fires `issues:closed` workflow, stamps done, no AI call. Labels become `[]`. Cost $0.

**Sentinel runs:** Implicit — validated in post-merge cleanup of every happy-path smoke.

**Retry after:** `is_closed` path in `preflight.py`, `mark_done` in work adapter.

---

## 8. Idempotency — duplicate event delivery

**What it validates:** `check_idempotency` rejects a second dispatch with the same `run_id`, no double-charge.

**Setup:** Trigger the same workflow twice rapidly (e.g., add `agent` label, remove, re-add within seconds).

**Expected:** Second run returns early with `error="duplicate_run_id"`, no AI call, no state change. Visible in GHA log as `dispatch.duplicate_run_id`.

**Sentinel runs:** _TBD — not easily producible manually; relies on `run_id` derivation from `event.key + stage + git_head_sha` being identical across runs._

**Retry after:** `_derive_mode2_run_id` in `cli/dispatch.py`, `check_idempotency` in `state_storage`.

---

## Open gaps — scenarios this plan doesn't yet cover

- Concurrent tickets racing on `cleanup_base` or state writes (the rebase-retry band-aid landed; not live-tested).
- Mid-stage runner death (timeout / cancelled). Depends on `fork_session` behavior in SDK.
- Multiple consumer workflows hitting the engine at once (cross-repo isolation).
- Non-trivial directive combinations (`base: feature/x` + `gate_merge: human` + feedback loop).

## How to cite this plan in a commit

> Retest scenarios: 1 (happy path), 3 (QUESTIONS resume) per `docs/test_plan.md`.

Keep a `Sentinel runs:` line per scenario updated as runs accumulate —
future sessions should be able to answer "was this validated in prod
recently?" without re-running the smoke.
