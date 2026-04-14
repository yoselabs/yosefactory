# Feedback-Aware Pipeline with Handover Pattern

Design for extending the a2sdlc pipeline to handle human and AI tool feedback, with stages as independently deployable products and a uniform context model.

## Context

### Problem

The current pipeline runs SPEC -> IMPLEMENT -> REVIEW -> MERGE linearly, with one feedback loop (REVIEW.changes_requested -> IMPLEMENT). But real-world feedback comes from many sources:

- Human engineers leaving PR inline comments or general PR comments
- Human QA/BA leaving comments on the issue/ticket
- AI tools (CodeRabbit, Copilot) posting PR review comments
- Human code reviewers submitting PR reviews with "changes requested"

The engine has no mechanism to collect this feedback, route it to the agent, or distinguish "this comment is for the AI" from "this is a human-to-human conversation."

### Goals

1. Agent can receive and act on feedback from any source (human, AI tool)
2. Each stage remains independently observable (separate CI job, separate comment, separate log)
3. Stages can be deployed standalone (e.g., REVIEW as a GitHub Action on any repo)
4. Architecture supports GitHub, GitLab, Forgejo, and Jira (build for GitHub first)
5. No external server or queue — everything runs inside CI

### Non-Goals (Backlog)

- Inline PR comment threading (agent replies to specific code line threads)
- Semantic noise filtering (NLP-based "is this for the AI?")
- CodeRabbit/Copilot special handling (advisory vs authoritative weighting)
- Custom dashboard or owned UI
- GitLab cron sweep (design supports it, build later)
- Jira adapter implementation (design supports it, build later)

## Architecture Overview

### Core Principles

1. **CI is the execution layer.** No external server, no queue, no webhook receiver. The engine runs inside CI jobs triggered by native platform events.
2. **One stage per CI job.** Each stage has its own log, its own comment, its own timing. Always.
3. **Event-triggered, state-reconciled.** Events (labels, comments) wake the engine. The engine reads full current state and decides what to do. It doesn't react to the event content — it reconciles.
4. **@mention gating for comments.** Comments only trigger the engine if they contain `@a2sdlc`. PR review submissions always trigger (no @mention needed). Label events always trigger.
5. **Handover comments as inter-stage contracts.** Each stage produces a structured comment that becomes the primary input for the next stage.
6. **Stages are functions, not deployment units.** The same stage code runs standalone (thin Action wrapper) or in the pipeline (engine calls it). The caller decides context and routing.

### Trigger Model

Two event paths in the CI workflow:

| Event | Filter | Purpose |
|-------|--------|---------|
| `issues.labeled` | None (always process) | Stage transitions via labels |
| `issue_comment.created` | `contains(body, '@a2sdlc')` | Human/tool feedback on issues |
| `pull_request_review.submitted` | `sender.type != 'Bot'` | Code review submissions (always actionable) |
| `pull_request_review_comment.created` | `contains(body, '@a2sdlc')` | Inline PR feedback |

Label events include bot-set labels (intentional stage transitions). Comment events require @mention to filter noise. PR review submissions are always actionable because submitting a review is a deliberate act directed at the PR (and by extension, the agent).

Reference CI workflow:

```yaml
on:
  issues:
    types: [labeled]
  issue_comment:
    types: [created]
  pull_request_review:
    types: [submitted]
  pull_request_review_comment:
    types: [created]

jobs:
  dispatch:
    if: |
      (github.event_name == 'issues') ||
      (github.event_name == 'issue_comment' && contains(github.event.comment.body, '@a2sdlc')) ||
      (github.event_name == 'pull_request_review' && github.event.sender.type != 'Bot') ||
      (github.event_name == 'pull_request_review_comment' && contains(github.event.comment.body, '@a2sdlc'))
    concurrency:
      group: a2sdlc-${{ github.event.issue.number || github.event.pull_request.number }}
      cancel-in-progress: false
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: a2sdlc dispatch
```

Concurrency: one group per ticket/PR. At most 1 running + 1 pending. Intermediate triggers are dropped, but nothing is lost because the pending run reads all current state (pull-based model).

### Bot Comment Filtering

The engine already filters bot-authored comments (github.py line 66). For label events, bot actions are intentional (stage transitions) and are always processed. The @mention filter on comment events provides the additional "is this for the AI?" signal. No separate bot identity per stage — single `a2sdlc` identity.

GitHub Apps do not receive webhook events for actions performed with their own installation token by default. But since we use GitHub Actions (not App webhooks), ALL events fire including bot-generated ones. The `if:` condition in the workflow handles filtering.

### Platform Compatibility

| Capability | GitHub | Forgejo | GitLab (future) | Jira (future) |
|-----------|--------|---------|-----------------|---------------|
| Label triggers | `issues.labeled` | `issues.labeled` | Webhook -> trigger API | N/A (use status) |
| Comment triggers | `issue_comment` | `issue_comment` | Webhook -> trigger API, or cron sweep | Cron sweep or Jira Automation webhook |
| PR review triggers | `pull_request_review` | `pull_request_review` (partial) | MR approval event | N/A |
| Concurrency | `concurrency` group | `concurrency` group | `resource_group` (queues, better) | N/A (CI-side) |
| Programmatic trigger | `repository_dispatch` | `workflow_dispatch` | Pipeline trigger API | N/A |

GitLab lacks native CI triggers for MR comments. The future path is either a lightweight webhook-to-trigger bridge or a cron sweep pipeline. The engine's pull-based model works with both — it reads current state regardless of how it was triggered.

Jira has no CI integration. The future path is Jira Automation (Cloud) posting a `repository_dispatch` webhook to GitHub/GitLab, or a cron sweep via JQL query scoped to tracked tickets only.

## Handover Pattern

### How It Works

Each stage produces a structured handover comment on the issue. The next stage reads the last handover comment as its primary context, plus any comments posted after it (feedback).

```
<!-- a2sdlc:handover stage=spec run_id=abc123 -->
## Specification Complete

### Acceptance Criteria
1. ...
2. ...

### Technical Approach
...

### Open Questions
None — all self-resolved with assumptions noted above.

---
*a2sdlc | spec | 45s | 12K tokens*
```

The HTML comment marker (`<!-- a2sdlc:handover ... -->`) is machine-readable. The rest is human-readable markdown.

### Context Assembly

The engine assembles context for each stage using one uniform algorithm:

1. **Find last handover comment** — scan issue comments for the `<!-- a2sdlc:handover -->` marker. This is the primary context.
2. **Collect post-handover comments** — all comments posted AFTER the last handover that contain `@a2sdlc` or are from the engine's own review. These are the feedback items.
3. **Collect PR state** (if PR exists) — diff summary, PR review comments with file/line metadata.
4. **Set system prompt mode hint** — one line: "You are implementing a fresh specification" vs "You are addressing review feedback on your previous implementation."

This is one code path regardless of whether it is a first run, a review cycle, or a human feedback cycle. The handover comment is the cursor — everything before it is history, everything after it is new input.

### No Separate "Modes" for IMPLEMENT

The IMPLEMENT stage does not need a "feedback mode" vs "fresh mode." The context assembly is uniform. What changes is the content:

- **First run**: handover = spec from SPEC stage, no post-handover comments. Agent implements from spec.
- **After AI review**: handover = implement report, post-handover = review feedback comment. Agent addresses review findings.
- **After human feedback**: handover = last implement report, post-handover = human's @a2sdlc comment. Agent addresses human feedback.

The system prompt hint tells the agent what to expect, but the context structure is identical.

### Avoiding the Telephone Game

Each handover comment is a checkpoint, not a summary of a summary. The original ticket body is always available as ground truth. Handover comments reference acceptance criteria by ID, not by re-describing them. The engine can detect drift by comparing handover content against the ticket body.

If the feedback loop runs 3 times, the agent sees: its most recent handover (not all 3) + the latest feedback. Context doesn't grow unboundedly.

## Human Gates

### Two Optional Gates

```
SPEC ──(optional: human reviews spec)──> IMPLEMENT -> REVIEW -> ... -> (pre-merge gate) -> MERGE
```

**1. Post-SPEC gate (optional)**

After SPEC completes, the engine checks `gates.spec`:
- `AUTO` (default): advance to IMPLEMENT immediately
- `HUMAN`: stop. Human reviews the spec comment. To proceed, human applies `proceed` label or leaves an @a2sdlc comment with approval.

If SPEC produces questions, behavior is configurable:
- `spec.self_answer: true` — agent makes assumptions and notes them
- `spec.self_answer: false` — waits for human answers (sets `needs-input` label)

**2. Pre-MERGE gate (required by default)**

After all automated stages pass (REVIEW approved, any future security/QA gates), the engine stops before MERGE. The human reviews:
- The code (PR diff)
- The test results
- A preview deployment (if configured)

The gate signal is configurable per adapter:

| Adapter | Gate signal |
|---------|-----------|
| GitHub | PR approval (non-bot reviewer) |
| GitLab | MR approval |
| Jira (future) | Ticket status = "QA Approved" or similar |
| Label-based | `proceed` label on issue |

### Feedback During Human Gate

When the human finds issues during pre-merge review:

1. Human leaves a comment: "@a2sdlc drag and drop doesn't work, please fix"
2. Comment event triggers CI job (passes @mention filter)
3. Engine reads TicketState: ticket is at pre-merge gate
4. Engine collects feedback (the human's comment)
5. Engine runs IMPLEMENT (context = last handover + human feedback)
6. IMPLEMENT fixes the code, produces handover comment
7. Engine advances: REVIEW runs (same CI job? NO — sets label, new CI job)
8. REVIEW passes, reaches pre-merge gate again
9. Human reviews again

Each step is a separate CI job with its own log and comment.

## Feedback Collection

### What the Engine Collects

When a comment-triggered run fires, the engine collects:

**From the issue/ticket:**
- All comments containing `@a2sdlc` posted after the last handover comment

**From the PR (if exists):**
- PR review submissions (all, regardless of @mention — reviews are inherently directed at the PR)
- PR inline comments containing `@a2sdlc`, with file path + line range metadata

**Format injected into agent context:**

```
## Feedback to Address

### PR Review by @jane (changes_requested)
General: "The error handling in the retry logic needs work."
- `src/a2sdlc/stages/implement.py` lines 45-52: "This swallows the original exception. Use `raise ... from`."
- `src/a2sdlc/stages/implement.py` line 78: "Missing timeout parameter."

### Issue Comment by @pm-bob
"When I test the preview, drag and drop doesn't work on mobile."
```

Human-readable, structured enough for the agent to act on. No JSON, no special parsing needed.

### What the Agent Produces

The agent fixes code and produces a handover comment summarizing what it did. The engine posts this comment. The engine does NOT post individual replies to each feedback item (backlog — would require the `respond_to_feedback` tool).

For now: one summary comment. Future: per-item responses.

### Noise Handling

The @mention filter eliminates most noise. For PR reviews (which don't require @mention): the engine includes them all, and the agent is smart enough to skip emoji-only or "LGTM" reviews. This costs a few tokens but avoids building a fragile heuristic pre-filter.

## Stages as Independent Products

### The Boundary

A stage is a function:

```
StageInput -> Stage -> StageResult + SideEffects
```

- **StageInput**: system prompt + user prompt (assembled by caller) + tool configuration
- **StageResult**: structured result (status, output text, metrics)
- **SideEffects**: comments posted, labels changed, code pushed (via adapters passed by caller)

The stage does not know whether it is running standalone or in a pipeline. The caller (engine or Action wrapper) handles context assembly, adapter wiring, and result routing.

### Standalone Deployment

A stage deployed as a standalone GitHub Action:

```yaml
# .github/workflows/review.yml
on:
  pull_request:
    types: [opened, synchronize]
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: yoselabs/a2sdlc-review@v1
```

The Action wrapper:
1. Reads the PR diff and comments
2. Assembles context for the REVIEW stage
3. Calls the stage function
4. Posts the review as a PR comment
5. Exits (no state machine, no labels, no pipeline)

### Pipeline Deployment

The same stage code, called by the engine:
1. Engine assembles context (handover + feedback + PR state)
2. Engine calls the stage function
3. Engine reads the StageResult for routing decisions
4. Engine posts the handover comment
5. Engine sets label for next stage

### Packaging

- `a2sdlc` (core): stage definitions, adapter protocols, contracts
- `a2sdlc` (engine): orchestrator, state machine, dispatch logic
- `a2sdlc-review`, `a2sdlc-implement`, etc. (Actions): thin wrappers (~50 lines) that import stage from core and wire to CI events

## Concurrency and Reliability

### CI Concurrency Groups

One group per ticket: `a2sdlc-${{ issue_number }}`. At most 1 running + 1 pending. Intermediate triggers are dropped.

**Why dropped triggers are OK:** The pull-based model means the engine reads ALL current state on each run. If 5 comments arrive and only 2 CI jobs run, the second job sees all 5 comments. The trigger is just a wake-up signal — the data is in the comments, not in the trigger.

### The Dead-Zone Edge Case

If the last comment in a burst arrives after the pending job's slot is already occupied AND after the running job has finished reading comments, that comment is orphaned until the next trigger.

**Mitigations:**
1. The pending job (when it runs) will read that comment too — it reads ALL comments since last handover, not since its trigger event.
2. If a human is actively reviewing, they'll likely trigger another event soon.
3. For critical cases: the human can re-trigger by applying a label or posting another @mention.

This is a latency failure, not a data loss failure. The comment is never lost — it's always readable on the next run.

### Self-Re-Trigger (Future Enhancement)

At the end of a run, the engine could check: "did new @a2sdlc comments appear since I started reading?" If yes, fire a `repository_dispatch` to re-check. This closes the dead-zone gap but adds complexity. Deferred — the pull-based model is sufficient for current usage patterns.

## Review Stage Contract

### Current Behavior (verdict-based)

The REVIEW stage currently produces a verdict (approved/changes_requested) that the engine interprets for routing.

### New Behavior (comment-based + verdict)

The REVIEW stage posts feedback as a PR comment (like CodeRabbit or Copilot code review) AND returns a structured verdict to the engine. This means:

- Humans see the review feedback as a normal PR comment
- The engine uses the verdict for routing (advance or loop back)
- If running standalone, the PR comment is the only output (verdict is ignored)
- The review comment follows the same handover format with the `<!-- a2sdlc:handover -->` marker

This creates a uniform interface: human review feedback, AI review feedback, and CodeRabbit feedback all look the same on the PR.

## Configuration

```yaml
# a2sdlc.yaml
pipeline:
  gates:
    spec: auto          # auto | human
    merge: human        # auto | human (human = require PR approval)
  spec:
    self_answer: true   # if spec has questions, agent makes assumptions
  review:
    max_cycles: 3       # circuit breaker for review loops
  trigger:
    mention: "@a2sdlc"  # configurable trigger phrase
```

## State Machine

```
                    ┌─────────────────────────────────────────┐
                    │                                         │
SPEC ──(gate)──> IMPLEMENT ──(auto)──> REVIEW ──(gate)──> MERGE
                    ^                     |
                    |                     |
                    └── changes_requested ┘
                    ^
                    |
                    └── human feedback (@a2sdlc comment)
```

Transitions:

| From | Result | Gate | Next |
|------|--------|------|------|
| SPEC | complete | spec: auto | IMPLEMENT |
| SPEC | complete | spec: human | wait for human |
| SPEC | questions | spec.self_answer: true | SPEC (self-answer, same run) |
| SPEC | questions | spec.self_answer: false | wait for human |
| IMPLEMENT | complete | review: auto (hardcoded, no human gate between impl and review) | REVIEW |
| REVIEW | approved | merge: auto | MERGE |
| REVIEW | approved | merge: human | wait for human approval |
| REVIEW | changes_requested | - | IMPLEMENT |
| any gate | @a2sdlc comment | - | IMPLEMENT (feedback is always treated as implementation-level; if it is truly a spec change, the agent can flag it in its handover comment) |
| MERGE gate | PR approved | - | MERGE |

## What Changes in Existing Code

### New in Adapters

- `ReviewAdapter.collect_pr_feedback(since: datetime) -> list[FeedbackItem]` — reads PR review comments and inline comments with metadata (author, file, line range, body)
- `WorkAdapter.collect_issue_feedback(key, since: datetime) -> list[FeedbackItem]` — reads issue comments containing the trigger phrase
- `WorkAdapter.find_last_handover(key) -> HandoverComment | None` — finds the last comment with the `<!-- a2sdlc:handover -->` marker on the issue
- `ReviewAdapter.find_last_handover(pr_number) -> HandoverComment | None` — finds the last handover comment on the PR (REVIEW stage posts on PR, not issue; engine searches both locations)

### Changed in Dispatch

- Context assembly uses the handover pattern (find last handover + collect post-handover feedback)
- `parse_event()` extended to handle new event types: `issue_comment` (extracts ticket key from issue, sets `is_feedback=True`), `pull_request_review` and `pull_request_review_comment` (extracts ticket key from PR, sets `is_feedback=True`)
- When `is_feedback=True`, the engine routes to IMPLEMENT regardless of current stage (feedback always re-enters the pipeline through implementation)
- Feedback items injected into agent user prompt as structured markdown

### Changed in Stages

- REVIEW stage posts feedback as PR comment (in addition to returning verdict)
- Handover comment format standardized across all stages

### New CI Workflow Events

- `issue_comment.created` with @mention filter
- `pull_request_review.submitted` with bot filter
- `pull_request_review_comment.created` with @mention filter
- `concurrency` group per ticket

### Not Changed

- Stage execution logic (runner.py)
- Tool configuration per stage
- State machine transitions (stages/__init__.py) — only extended, not restructured
- One stage per CI job model
