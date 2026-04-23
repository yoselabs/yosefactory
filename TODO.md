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

## Test infrastructure follow-ups

- [ ] `make test` wall-clock is 18-34s under xdist; pytest itself is ~11s. The extra time is coverage finalization + the serial pass exit-5 dance. If the gap becomes painful, drop coverage from the default dev loop (keep it in `make check`) or skip the serial pass when no `@pytest.mark.serial` tests exist.
- [ ] Zero tests currently marked `@pytest.mark.serial`. Preserve this as an invariant — any new `serial` mark should come with a follow-up ticket to deflake.

## Track C — post-v0.2.0 polish + coverage (from 2026-04-22 session)

### Bugs caught in smoke #28 (breaker validation)

- [ ] Duplicate `Blocked:` comment on breaker trip. `check_cost_ceiling` / `check_review_cycles` call `mark_blocked(reason)` in preflight, then the CLI's error-handler wrapper in `cli/dispatch.py` ALSO calls `mark_blocked(f"Stage failed: {reason}")` because it treats the `DispatchResult(blocked=True)` return as an error. Fix: make the CLI wrapper distinguish "pre-execution breaker trip" (clean exit) from "mid-stage exception" (error path with traceback). Dedupe path already exists in `mark_blocked` but the message differs (`"Cost ceiling..."` vs `"Stage failed: Cost ceiling..."`), so the existing scan-for-duplicate check misses it.
- [ ] Workflow exit code `failure` on clean breaker trip. `DispatchResult(blocked=True, error=<breaker-reason>)` propagates as Typer non-zero exit → workflow fails. Consumers see a red X on breaker trip even though behavior is correct. Fix: either (a) CLI exits 0 when `blocked=True` AND `error` matches a known-breaker reason, or (b) add a dedicated `breaker_tripped` field on `DispatchResult` that CLI checks.

### Cassette seeding for GH adapter integration tier (blocked on user)

- [ ] Run `GITHUB_TOKEN=ghs_... make record-integration` once with a real installation token from the smoke repo's App. Commits cassettes to `tests/integration/adapters/cassettes/`. Unblocks CI-level auth-mode regression catching (see `Evolution/signals/2026-04-21-2341-unit-tests-miss-gh-token-auth-bugs.yaml` for context). Scrubber strips `authorization` + cookies before cassettes hit disk — still diff before committing.

### Smoke scenarios still not live-validated (docs/test_plan.md)

- [ ] **Scenario 4 — human PR review feedback loop.** Prereq: a ticket sitting in REVIEW with `gate_merge: human`. Submit PR review with `CHANGES_REQUESTED` + specific feedback comment. Expect engine to route to IMPLEMENT with feedback, increment `review_cycles`, REVIEW re-approves, MERGE. Cost ~$3, ~15 min. Retry after any `feedback_routing.py` / review-adapter / cycle-counter change.
- [ ] **Scenario 6 — stage-override directives.** Prereq: a `develop` branch on smoke repo. Ticket body includes `base: develop\n---\n<body>` or `gate_merge: human`. Expect branch `agent/{N}` against `develop`, MERGE blocks on human approval despite project config `gates: {merge: auto}`. Cost ~$3. Retry after `domain/directives.py` / `preflight.py` gate-merging changes.
- [ ] **Scenario 5a — review-cycle breaker live.** Lower priority — mechanism already validated by 5b (cost-ceiling) in smoke #28. Skip unless the cycle-counting logic in `breakers.py` changes.
