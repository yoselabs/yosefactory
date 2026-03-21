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
- [ ] Engine CI — run tests on push to agentic-eng/a2sdlc
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

## Known Issues

- [ ] `git add -u` equivalent needed — commit_artifacts takes explicit paths but we might miss files the agent created
- [ ] Concurrency: if two label events fire simultaneously for the same issue, both jobs run
- [ ] No `needs-input` label management in dispatch — agent sets it via prompt, engine doesn't verify
