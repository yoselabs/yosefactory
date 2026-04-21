# Mode 2 Hardening — Session Outcome

**Date:** 2026-04-21 (same calendar day as the initial smoke handover)
**Branch:** `feat/mode2-smoke-telemetry` — now ~150 commits ahead of `main`
**Smoke repo:** `iorlas/a2sdlc-smoke` — 3 tickets run, main cleaned
**MLflow:** `mlflow.shen.iorlas.net` experiment `a2sdlc-smoke`

## TL;DR

End-to-end Mode 2 automation is now verified — ticket #10 (`--version`
flag) flowed spec → implement → review → merge → done with zero human
intervention on the final pass. 16 new commits landed on top of the
original smoke branch, covering correctness, idempotency, and a
tracker-agnostic direction for Phase 2.

All 4 architectural-decision questions posed to the user are settled.
542 tests pass.

## What changed this session

### New tickets run against the smoke repo

| # | Shape | Outcome |
|---|---|---|
| #2 | Extend existing (`--format json`) | Merged cleanly (after manual PR approval) |
| #8 | New subcommand (`search`) | State-leak bug mid-flight → closed, fixed structurally |
| #10 | New flag (`--version`) | End-to-end auto-merge verified |

### Commits landed (in merge-order)

| Commit | Area | Fix |
|---|---|---|
| 56cf481 | logging | `_JsonFormatter` preserves `extra={...}` kwargs |
| 3f046ca | mode2 | `create_draft_pr` reuses existing open PR; `set_stage_label` strips `agent` |
| d63a683 | chore | gitignore `mlflow.db` |
| 0871786 | adapter | Skip closed-issue labeled events (later superseded) |
| 026afd4 | dispatch | Engine-level `WorkAdapter.is_ticket_active` contract |
| 24abaf8 | merge | Narrow commit paths; add strip_runtime (later superseded) |
| a78b404 | dispatch | Read state AFTER branch setup, not before |
| c818380 | docs | UX audit notes (state-leak bug) |
| 43f3832 | review | `mark_pr_ready` uses GraphQL, not REST PATCH |
| de4fe90 | merge | Post-merge `cleanup_base` (replaces pre-merge strip) |
| f93cc0e | work/github | `set_done_label` replaces prior stage labels |
| 26fd293 | docs | Ticket #10 end-to-end verification notes |
| 9893d23 | docs | Prioritized P0/P1/P2 follow-ups doc + TODO prune |
| 4ec223b | mode2 | Idempotency (`run_id`), issues:closed, error UX, GHS sniff, dup suppression |
| 76903ae | review | Idempotent `merge_pr` + deduped `post_review` fallback |
| 3be4a23 | work | Drop `stage:done` label; add `get_current_stage`; native closed = done |

### Correctness & idempotency bugs fixed

- JSON logs dropped `extra={...}` → now preserved.
- `_commit_and_push` committed whole `.a2sdlc/` → now narrow (`state.json` + `docs/`).
- `create_draft_pr` 422 on retry → reuses existing open PR.
- State `.a2sdlc/state.json` leaked into base on squash-merge → `cleanup_base` post-merge.
- `state_mgr.read_state()` ran before `setup_branch` → reordered.
- `mark_pr_ready` used REST PATCH (silently no-op) → uses GraphQL.
- Pre-merge `strip_runtime` deleted state on failure, lost retry → post-merge `cleanup_base` keeps state through retries.
- `merge_pr` 405 on already-merged retry → guards with `pull.merged` check.
- `post_review` APPROVE self-approval 422 → silently skipped (verdict lives in issue comment).
- `post_review` non-422 fallback duplicated comments on retry → dedupes by marker.
- `set_blocked` stacked duplicate "Blocked:" comments → dedupes by last-10 scan.
- `set_stage_label` didn't clean up `agent` trigger → now strips it on transition.
- `set_done_label` added redundant `stage:done` → now closes issue + strips labels.
- Closed-issue label events re-ran AI stages → `is_ticket_active` short-circuits.
- `issues:closed` action ignored → emits `is_closed=True`, dispatch marks done.
- Missing Mode 2 idempotency → `ctx.run_id` derived from event trigger_id + SHA.
- GHA default `ghs_` token breaks state machine silently → `typer.BadParameter` at startup.
- Uncaught dispatch exceptions → issue comment with Actions run URL; traceback stays in CI.

### New contracts

- `WorkAdapter.is_ticket_active(key) -> bool` — terminal-ticket guard.
- `WorkAdapter.get_current_stage(key) -> StageName | None` — tracker-agnostic stage read.
- `GitAdapter.cleanup_base(base) -> bool` — post-merge base hygiene.
- `PipelineEvent.is_closed: bool` — human-closed ticket signal.

## Architectural decisions settled

| # | Decision | Status |
|---|---|---|
| Reviewer identity | Keep current behavior — engine APPROVE review is redundant with `check_human_approval`; 422 silently skipped; humans approve via native UI; REQUEST_CHANGES self-reviews still work. No PAT, no second App. | CLOSED |
| `stage:done` label | Dropped in favor of native issue-closed state. `set_done_label` closes the issue + strips `stage:*` + `agent`. Maps cleanly to Jira's "Done" status. | LANDED |
| Concurrency | Keep queue semantics (`cancel-in-progress: false`). Idempotency makes stale events cheap; cancel-in-progress creates orphan progress comments. | KEPT |
| WorkAdapter protocol | Greenlit for tracker-agnostic abstraction. First additive slice (`get_current_stage`) landed. Full rename + pipeline-ledger relocation queued as a separate PR. | STARTED |

## What's still open

Tracked in detail in `docs/superpowers/handovers/2026-04-21-mode2-followups.md`.

**P0 (phase-2 blockers):**
- Full WorkAdapter rename (`set_stage_label` → `set_current_stage`, `set_blocked` → `mark_blocked`, `set_done_label` → `mark_done`).
- Pipeline-ledger relocation off the ticket branch (orphan branch for GH, dispatcher KV for Jira).
- `cleanup_base` push-rebase retry for the concurrent-merge race (~10 LOC tactical).

**P1:**
- Consumer onboarding docs (required secrets, `gates.merge: auto`, minimum `a2sdlc-run.yml`).
- MLflow `session_id` collision for parallel A/B runs on the same ticket.
- Post-squash double-close dedup (engine sets done, then GH close event arrives, dispatch re-runs `set_done_label` — idempotent now, but worth skipping earlier).

**P2:**
- "Agent" tool row has empty target in timeline.
- Stage comments don't link to the PR.
- `needs-input` label UX for SPEC `QUESTIONS` verdict.
- Cost ceiling per ticket.

**Scenarios not yet exercised:**
- Concurrent tickets on different issues (race on `cleanup_base`).
- Human PR review comment → engine IMPLEMENT re-run.
- Circuit breaker firing (≥ max review cycles).
- Mid-stage runner death + resume.
- Ambiguous ticket → SPEC asks questions.
- Stage-override directives in ticket body (`base:`, `gate_spec:`).

## Smoke repo state

- Main: clean (`.a2sdlc/config.yaml` only).
- Issues #2, #8, #10 closed.
- PRs #7, #11 merged.
- PR #9 closed without merging (post-cleanup conflict; was for ticket #8).
- Secrets configured, gate set to `merge: auto`.

## Branch state

`feat/mode2-smoke-telemetry` is ~150 commits ahead of main. All 542 tests
pass. `make check` is green. Workflows still pinned to
`@feat/mode2-smoke-telemetry` — reset to `@main` when merging.

## Merge-to-main checklist

1. Un-pin workflow refs:
   - `.github/workflows/run-native.yml:40`
   - `.github/workflows/run-split.yml:72`
   - Consumer repo workflow (`iorlas/a2sdlc-smoke/.github/workflows/a2sdlc-run.yml`)
2. `make check` clean (last run: green).
3. Squash or curated merge. If squashing, consider grouping: telemetry
   rewiring → parallel tests → workflow hardening → state-hygiene →
   idempotency/dedup → tracker-abstraction-start.
4. After merge, smoke repo can be kept as a permanent fixture.
