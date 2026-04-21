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

- [ ] JSON log formatter doesn't include `extra` fields — structured log data (reason, stage, cost) is invisible in CI
- [ ] All `logger.info("dispatch.*", extra={...})` calls produce logs without the extra context
- [ ] Fix: update `setup_logging()` formatter to include extra fields in JSON output
- [ ] All warnings and errors from adapters should be visible in CI logs for tracing

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

## Mode 2 auth/trigger follow-ups

- [ ] Engine-side idempotency for Mode 2: `cli/dispatch.py` Mode 2 branch doesn't set `run_id`, so `check_idempotency` is skipped. When two events for the same issue reach `pipeline.dispatch()` simultaneously, both execute the stage. Workflow `concurrency:` group serializes at GHA level, but stage runs that re-trigger themselves (e.g. push after commit → issues event) can still re-enter. Derive `run_id` from `f"{ticket_key}:{stage}:{head_sha}"` or similar and enforce idempotency in-engine.
- [ ] Engine-side token sniff: `cli/dispatch.py` should detect a `ghs_`-prefixed `GITHUB_TOKEN` (the GitHub Actions default) and refuse to run with a clear error. Current behavior (silent non-triggering) breaks the state machine invisibly. Fail-early matches the workflow preflight we added.
- [ ] `agent` label lingers on issue after `stage:implement` is set — engine should remove `agent` when it transitions to any `stage:*`. Observed during first successful run.
- [ ] Existing-PR reuse in SPEC stage: `GitHubReviewAdapter.create_draft_pr` should look up an existing PR by `head=branch` and return its number instead of raising 422. Retry-safety after partial failures.

## Test infrastructure follow-ups

- [ ] `make test` wall-clock is 18-34s under xdist; pytest itself is ~11s. The extra time is coverage finalization + the serial pass exit-5 dance. If the gap becomes painful, drop coverage from the default dev loop (keep it in `make check`) or skip the serial pass when no `@pytest.mark.serial` tests exist.
- [ ] Zero tests currently marked `@pytest.mark.serial`. Preserve this as an invariant — any new `serial` mark should come with a follow-up ticket to deflake.
