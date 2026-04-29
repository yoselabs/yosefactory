# a2sdlc TODO

## Progress Comment Redesign (I0239)

- [ ] Tool content in progress — `Read {path}`, `Edit {path}:{line}`, `Bash: {command[:60]}` instead of just tool names
- [ ] Turn counter — `(turn N/max)` in progress comment
- [ ] Running token/cost totals — accumulate from AssistantMessage.usage during streaming
- [ ] Context fill % — show how much of the context window is used
- [ ] Model name — show which model is running in the status bar
- [ ] Milestone sections — implementation, review 1, review 2 don't disappear when logs update
- [ ] Agent text messages — TextBlock content (truncated) appears in logs
- [ ] Status bar — reused across all stages, shown in final comment as summary
- [ ] Icons — scannable at a glance
- [ ] Turn exhaustion — if max turns reached, dispatch marks stage as `stage:blocked`
- [ ] Move progress updates from hook-based (on each tool call) to timer-based (every 3s) — decouple from SDK streaming events so updates happen reliably regardless of tool activity
- [ ] Skill invocations should persist in the log (not disappear when overwritten) — e.g. "brainstorming invoked at 0:42", "writing-plans invoked at 2:15"
- [ ] Tool calls should include timestamp (relative to stage start) — "0:42 Read src/app.py", "1:15 Bash: pytest"
- [ ] Consider table format for tool log — columns: time, tool, target, result. Make it scannable and visually appealing

## Code Review Milestones

- [ ] Detect `/requesting-code-review` invocation as a milestone boundary
- [ ] Show per-milestone log sections: "Implementation + last N logs", "Review 1 + last N logs", "Review 2 + last N logs"
- [ ] Final comment shows all milestones collapsed with status bar summary

## Review Stage Comment Routing

- [ ] Review stage posts full result on the PR, not the issue
- [ ] Issue gets a short summary: "Review complete: APPROVED. See PR #N for details."
- [ ] Avoids duplicate content (currently full review on both issue and PR)
- [ ] Related: post_review fallback posts a comment when self-approval fails — this becomes the primary path until separate review identity is configured

## Review Stage Context

- [ ] Review stage should receive original issue description (the requirement)
- [ ] Review stage should receive the spec document (what was planned)
- [ ] Review stage should receive issue comments (Q&A context from spec stage)
- [ ] Reviewer checks "does this PR implement what was asked?" not just "is the code correct?"
- [ ] Currently reviewing code quality in isolation — doesn't know the original intent

## Pipeline Features

- [ ] `base:` parsing from ticket body (custom base branch per ticket)
- [ ] `auto_spec` prompt — move from hardcoded prefix to a prompt file
- [ ] `proceed` label reads state.json to determine resume stage (full implementation — currently simplified to always IMPLEMENT)
- [ ] Deploy stage (post-merge deployment trigger)
- [ ] Staleness revalidation (recheck spec after long delay before implement)
- [ ] Review-to-spec loop (review rejection goes back to spec, not just implement)
- [ ] Cost budgets per ticket
- [ ] Ticket batching (consolidate similar tickets into one spec)

## Adapters

- [ ] Jira adapter — reimplement as TicketAdapter protocol
- [ ] GitLab adapter
- [ ] SdkRunner — extract from inline class in cli.py to proper module

## Infrastructure

- [ ] Docker image for CI (eliminate 2-min install overhead per stage)
- [ ] Retry/backoff on GitHub API calls (PyGithub)
- [ ] Engine CI — run tests on push to yoselabs/a2sdlc
- [ ] Flow trace review step — walk through each UC end-to-end across systems before shipping

## Status Block Robustness

- [ ] Agent sometimes doesn't produce the `a2sdlc` status block (especially when confused or hitting limits)
- [ ] Add heuristic fallback: if output mentions spec/plan files but no block → treat as complete
- [ ] Add stronger prompt reinforcement: repeat the status block requirement at the end of the prompt
- [ ] Log the full agent output when no status block found (for debugging)

## Logging

- [ ] All warnings and errors from adapters should be visible in CI logs for tracing
- [x] JSON log formatter preserves `extra={...}` fields — fixed 2026-04-21 (56cf481)

## Idea: Agent Record block inside issue body

Cross-platform ticket layout (GitHub/Jira/GitLab — all render markdown checklists) where the issue body has two zones:

- **Human zone** (contract): pinned Gherkin scenario, artifact links (spec.md, plan.md, PR), scope/rabbit-holes metadata. Read-only for agents.
- **Agent zone** (delimited by `<!-- agent-record:start -->` / `<!-- agent-record:end -->`): agent-owned, contains:
  - **Stages** fixed list — `[ ] Spec / Plan / Implement / Review` — ticked as stages complete
  - **Implementation tasks** append-as-discovered during plan + impl, checked when done — gives live visibility into progress without separate sub-issues

Rules:
- Agent reads body, mutates **only** between the markers, preserves everything else verbatim
- Timestamps + narrative go in comments (append-only), not body — keeps body diff clean
- Discovery itself is the "appearing" signal; skip a separate in-progress state (noisy, collision-prone)
- Body footer carries the contract: `<!-- agent-contract: body outside agent-record is human-authored. Agents: do NOT edit. -->`

Context: convergent industry practice (Copilot coding agent, Claude Code Action, Port, SpecKit) is "human owns body, agent comments + labels + checklist." This formalizes the agent-writable surface so sdlc agents can report stage + live task progress inside the same ticket without risking collisions with human edits. Cross-platform because markdown checklists work everywhere; Jira native sub-tasks are heavier and platform-locked — upgrade later if needed.

Related: BMad's "Agent Record" section in story files, but real-time + tracker-native instead of file-based.

## Known Issues

- [ ] `git add -u` equivalent needed — commit_artifacts takes explicit paths but we might miss files the agent created
- [ ] Concurrency: if two label events fire simultaneously for the same issue, both jobs run
- [ ] No `needs-input` label management in dispatch — agent sets it via prompt, engine doesn't verify

## Telemetry follow-ups (post-Mode-2-smoke)

- [ ] Mode 2 parallel-run race: `MlflowTelemetry.session` duplicates parent runs when two jobs share a `session_id`. Derive session id from `run_id` (ticket_key:run_id) to isolate parallel A/B runs. See `feedback_parallel_runs` memory + the comment in `packages/engine/src/a2sdlc/evaluation/telemetry.py`.
- [ ] `cli/dispatch.py` Mode 2 branch doesn't set `run_id` on `DispatchContext` — check_idempotency is skipped. Pre-existing; surface was widened by telemetry wiring which now keys off session_id.
- [ ] `MlflowUnreachableError` surfaces as a bare Python traceback through Typer. Wrap in `dispatch_command` and re-raise as `typer.BadParameter` for cleaner CLI UX on misconfigured env.

## Mode 2 hardening follow-ups

See `docs/superpowers/handovers/2026-04-21-mode2-followups.md` for the
full prioritized list (P0 / P1 / P2) and Phase 2 ship criteria.

Short version of what's still open:

- **P0.1** Mode 2 engine-level idempotency (`ctx.run_id`)
- **P0.2** Reviewer identity (recommend option (c): skip PR review API)
- **P0.3** State storage race on concurrent merges (short-term retry, medium-term orphan branch)
- **P0.4** Label ≡ state.json coherence
- **P0.5** Error UX — tracebacks in CI instead of structured issue comment
- **P1.1** Engine-side `ghs_`-prefixed token sniff
- **P1.2** `issues:closed` → engine cleanup
- **P1.3** Suppress duplicate PR fallback comment on APPROVE self-review
- **P1.4** Document `gates.merge: auto` and required secrets for consumers

Fixed this session (2026-04-21):

- [x] `agent` label lingers alongside `stage:*` (3f046ca)
- [x] Existing-PR reuse in SPEC stage (3f046ca)
- [x] Engine-level closed-issue / ticket-not-active contract (026afd4)
- [x] Per-ticket state leaking into base branch on squash-merge (24abaf8, de4fe90)
- [x] Read state AFTER branch setup (a78b404)
- [x] `mark_pr_ready` uses GraphQL, not REST PATCH (43f3832)
- [x] `set_done_label` replaces prior stage labels (f93cc0e)

## Gates via labels, directives for overrides (design — 2026-04-23)

- [x] Move the common per-ticket gate controls onto **labels** rather than body directives. Phase 1 shipped 2026-04-28 (e993c13): label parser + label-wins merge + ingress re-reads labels fresh each dispatch. Mapping live now — `gate:merge:human` / `gate:merge:auto` / `gate:spec:human` / `gate:spec:auto`. Bracket directives still parsed as the fallback when no matching label exists.
- [x] Keep `[a2sdlc ...]` bracket directives for **override** free-text knobs (`base=`, `model=`). Implemented as part of phase 1 — body-only fields preserved through `merge_directives`.
- [x] Live smoke validation 2026-04-28 (smoke #47): ticket filed with `agent` + `gate:merge:human` labels, no body directive. Engine opened draft PR #48, paused at REVIEW with `to:null`, my APPROVE routed direct to MERGE, engine squash-merged in 4s, state.json stripped from main. Label-form gate fully honored end-to-end.
- [x] Pre-create the four `gate:*` labels on the smoke repo (done 2026-04-28).
- [x] Phase 2 follow-ups:
  - [x] Update `docs/test_plan.md` scenarios 4 + 6 to recommend label form as the primary path; keep bracket form mentioned as fallback. (439b300)
  - [x] Consumer onboarding: `a2sdlc ensure-gate-labels` CLI subcommand creates the four `gate:*` labels idempotently. Run once per consumer repo with `GITHUB_TOKEN` + `GITHUB_REPOSITORY` set. Engine dispatch hot path does NOT auto-create — explicit avoids per-run API cost.

## SPEC-stage prompt leaks surfaced in smoke #38 (2026-04-23)

- [x] **SPEC agent authors `gh pr create` steps the engine is supposed to own.** Two-layer fix 2026-04-23: prompt guardrails added (9e4aeb3) — "What the engine owns" section in `prompts/stages/spec.md`; SDK-level PreToolUse hook (63b8604) denies any `gh pr create/edit/merge/ready/close/reopen/review`, `hub pull-request`, or `glab mr *` Bash invocation with an explanatory deny reason. Engine-global, 7 unit tests. Awaits live smoke revalidation.
- [x] **SPEC self-review hallucinated a "missing" directive value.** Fixed 2026-04-23 (9e4aeb3) — both self-review steps now require the reviewer to quote the exact line(s) from the spec/plan/ticket for every "missing/unclear/contradictory" finding. No-evidence findings are rejected. Awaits live smoke revalidation.

## Parked: state.json out of the working tree (2026-04-29)

Ideas for moving runtime state off the agent branch so manual-merge bypass can't leak it:

- **Orphan state branch (`_a2sdlc-state` or similar).** Files at `state/<ticket>.json`. Visible in branch list, files are clickable on github.com (engine could post `https://github.com/owner/repo/blob/_a2sdlc-state/state/<key>.json` in finalize comments for troubleshooting). Single timeline per ticket = `git log` audit trail. Concurrent-write races handled by push-with-rebase retry. Most attractive given Denis wants visibility for troubleshooting.
- **Custom refs (`refs/a2sdlc/state/<ticket>`).** Atomic compare-and-swap via `update-ref`. Cleanest race semantics but **invisible in GitHub UI** — no clickable troubleshooting URLs.
- **Hidden state comment on the issue.** Zero git plumbing, but exposes state in the issue page source and adds API calls per dispatch.
- **External state server.** Future option; not for v1, won't be for every consumer.

For now, `a2sdlc scrub-base` (this commit) covers the recovery case. Revisit if manual-merge bypass keeps biting in real smokes; the orphan-branch option also retires `strip_runtime_state` and the `e871e9d` branch-match guard once migrated.

## Cross-ticket PR contamination + opaque `_ensure_draft_pr` skips (smoke #42–#44)

- [x] **`_get_pr_for_branch` head filter missing `owner:` prefix.** Fixed 2026-04-23 (51b2851). Smoke #42 surfaced — agent/42 REVIEW dispatch resolved PR #29 (from agent/28, still OPEN). GitHub API ignores the head filter when no owner is included, so any OPEN PR can match. Added `owner:branch` format + `pr.head.ref == branch` defence-in-depth verification + skip-wrong-branch unit test.
- [x] **`_ensure_draft_pr` silently skipped creation on #42, #43, #46.** Root-caused 2026-04-28 in smoke #46 (e871e9d): manual merges (e.g. `gh pr merge` from CLI when the engine's MERGE-stage install step fails) bypass `strip_runtime_state`, leaving `.a2sdlc/state/state.json` on the base branch. The next SPEC dispatch inherits the stale state and reads someone else's `pr_number` — short-circuiting creation. Fix: branch-match guard (`state.pr_number` only trusted when `state.branch == intent.branch`); base branches scrubbed manually; diagnostic logs upgraded with `state_branch`/`intent_branch`/`state_owns_branch`. Validated end-to-end in smoke #47.

## Bugs caught in smoke #36 (scenario 4 retry, 2026-04-23)

- [x] **APPROVE reviews route to IMPLEMENT as if they were CHANGES_REQUESTED.** Fixed 2026-04-23 (0127e27) — `_parse_pr_review_event` checks `review.state` and skips dismissed, routes APPROVED as a proceed-shaped event (not feedback).
- [x] **Manual merge is the only way to clear `gate:merge=human`.** Fixed 2026-04-23 (28d9a6c) — human APPROVE now emits a proceed-shaped event; ingress routes past the merge gate via the handover-based advance path (REVIEW handover → MERGE). Human reviews; AI merges.

## Architecture follow-ups (from P8 — 2026-04-23)

- [x] **`stages/` is heavier than `docs/architecture.md` §2 claims.** Fixed 2026-04-23 (7d25cfb) via ctx-based injection: ExecutionResult moved to domain/, StageExecutor instantiated in pipeline/dispatch and exposed through RunContext.stage_executor. Stages dropped from cap-test EXEMPT; four `stages.* -> pipeline.stage_executor` whitelists retired. Each stage now imports from 4 packages.

## Test infrastructure follow-ups

- [ ] `make test` wall-clock is 18-34s under xdist; pytest itself is ~11s. The extra time is coverage finalization + the serial pass exit-5 dance. If the gap becomes painful, drop coverage from the default dev loop (keep it in `make check`) or skip the serial pass when no `@pytest.mark.serial` tests exist.
- [ ] Zero tests currently marked `@pytest.mark.serial`. Preserve this as an invariant — any new `serial` mark should come with a follow-up ticket to deflake.

## Track C — post-v0.2.0 polish + coverage (from 2026-04-22 session)

### Bugs caught in smoke #28 (breaker validation)

- [x] Duplicate `Blocked:` comment on breaker trip. Fixed 2026-04-23 (ad3b2c1) — CLI no longer calls `_notify_stage_failure` on `blocked=True`.
- [x] Workflow exit code `failure` on clean breaker trip. Fixed 2026-04-23 (ad3b2c1) — `blocked=True` exits 0 via clean Typer return.

### Cassette seeding for GH adapter integration tier

- [x] Seeded 2026-04-23 (b2c2ab7) via one-shot mint workflow on the smoke repo. All 13 cassettes recorded + scrubbed + committed. Replay active in `make check` via `make test-integration`.

### Smoke scenarios still not live-validated (docs/test_plan.md)

- [x] **Scenario 4 — human PR review feedback loop.** Validated 2026-04-23 via smoke #36 (retry after #34's directive-syntax mistake). See `docs/test_plan.md` §4 sentinel runs. Two engine bugs surfaced (APPROVE-as-feedback routing + no auto-MERGE on human APPROVE) — logged separately above.
- [x] **Scenario 6 — stage-override directives.** Validated 2026-04-23 via smoke #38. PR #39 opened against `develop` per `[a2sdlc base=develop]`; MERGE paused per `[a2sdlc gate:merge=human]`; manual squash-merge closed the loop. See `docs/test_plan.md` §6.
- [ ] **Scenario 5a — review-cycle breaker live.** Lower priority — mechanism already validated by 5b (cost-ceiling) in smoke #28. Skip unless the cycle-counting logic in `breakers.py` changes.
