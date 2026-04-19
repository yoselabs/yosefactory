# Shaping, GH-Native Runtime, and Jira Dispatcher — Design

**Date:** 2026-04-19
**Status:** Draft, pending user review
**Revision:** 2 (reordered: GH-native runtime is Day 1; Jira dispatcher is Days 2–3)

## Problem

Today a2sdlc is a per-ticket pipeline (SPEC → IMPLEMENT → REVIEW → MERGE). Two layers are missing to demo the full SDLC story end-to-end:

1. **Requirements → tickets.** There is no interactive shaping layer that turns vague requirements into a dependency-ordered set of tickets. Humans author tickets manually today.
2. **Ticket orchestration.** No component watches the tracker to launch pipeline runs for newly-unblocked tickets, nor to transition tickets when a PR merges.

We ship this in two milestones:

- **Day 1 — GH-only runtime (Mode 2):** Issues, Discussions, and Actions only. No server, no Jira. Validates the full loop (shape → schedule → build → PR → merge → unblock next) and gives the OSS/content pitch its first runnable artifact.
- **Days 2–3 — Jira+GH runtime (Mode 1):** adds a thin dispatcher service on Dokploy that fronts Jira and triggers the same engine in GH Actions. Purely additive on top of Day 1.

The local-eval workflow (`cli_local.py`) remains the third composition branch and is not regressed.

## Goals

1. **End-to-end automation** from "ticket ready" to "PR merged" to "next ticket ready." No human click-glue in between.
2. **One engine codebase, three composition modes** (local / GH-native / Jira-dispatcher), selected ambient from env. No mode flag, no dotfile switch.
3. **Engine is ticket-system-agnostic.** Jira-aware code lives only in the dispatcher; GH-aware code lives only in the `GH*` adapters.
4. **Target-repo install footprint is tiny:** 2 workflow files (Mode 2) or 1 workflow file (Mode 1). No secrets beyond Anthropic / MLflow / GITHUB_TOKEN. No per-repo mapping files.
5. **MLflow is a first-class telemetry subscriber** across all three modes. Activated by env var; silent when not set.
6. **Local eval workflow is preserved.** `feat/local-runner` behaviour continues to work unchanged as the fallback composition branch.
7. **Day 2–3 additions are purely additive.** No refactor of Day 1 code when the dispatcher lands.

## Non-Goals (v1)

- Multi-tracker deployment (Jira + Linear in the same dispatcher). One tracker per dispatcher.
- GitLab / Azure Boards / ClickUp adapters.
- Parallel A/B variant orchestration triggered from Jira/GH. Engine supports variants via `branches.prefix` and MLflow tagging; matrix orchestration is a cherry on top, deferred.
- Admin UI over projects config.
- Retry policies, DLQ, crash recovery.
- OIDC / token exchange. HMAC capability tokens only.
- Webhook-less "install one action" marketplace publication (comes after Day 1 ships).

## Architecture — Shared foundations

### Engine layout (uv workspace, flat layout under each package's src/)

```
./
├── pyproject.toml                    # workspace root (virtual)
├── uv.lock
├── packages/
│   ├── engine/                       # Day 1
│   │   ├── pyproject.toml            # name = "a2sdlc-engine"
│   │   └── src/
│   │       └── a2sdlc/               # existing code, unchanged imports
│   └── dispatcher/                   # Day 2
│       ├── pyproject.toml            # name = "a2sdlc-dispatcher"
│       └── src/
│           └── a2sdlc_dispatcher/
├── tests/
├── Dockerfile.engine
├── Dockerfile.dispatcher             # added Day 2
└── Makefile
```

Root `pyproject.toml`:

```toml
[tool.uv]
package = false

[tool.uv.workspace]
members = ["packages/*"]

[dependency-groups]
dev = ["pytest", "ruff", "mypy", "pytest-cov"]
```

Rationale: flat layout under each package keeps a single `src/` level per package (not nested), matches uv's reference docs, and follows PyPA's src-layout recommendation for library isolation.

### Adapter split — the load-bearing contract

Every ticket interaction is one of:

- **Input (read-once, at run start):** fetch the ticket body / context. Abstracted as `TicketInputReader`.
- **Output (emit throughout the run):** progress, comments, status changes. Piggybacks on the existing subscriber bus via a `TicketOutputSubscriber`.

Engine code never calls a ticket system directly. It reads once through the input reader; it emits events through the subscriber bus.

Implementations per mode:

| Mode | Input reader | Output subscriber |
|---|---|---|
| Local | `LocalFileReader` (existing `.a2sdlc/ticket.md`) | none (transcript + console + optional MLflow) |
| GH-native (Day 1) | `GHIssueReader` (gh API) | `GHIssueSubscriber` (comments + label transitions) |
| Jira-dispatcher (Day 2) | `WorkflowInputReader` (inputs passed by dispatcher) | `DispatcherEventSubscriber` (HTTP POST of domain events) |

### Env-driven composition root

```python
def build_input_reader() -> TicketInputReader:
    if os.getenv("DISPATCHER_URL"):
        return WorkflowInputReader(...)
    if os.getenv("GITHUB_ACTIONS") == "true":
        return GHIssueReader(token=os.environ["GITHUB_TOKEN"], ...)
    return LocalFileReader(...)

def build_subscribers() -> list[Subscriber]:
    subs: list[Subscriber] = [ConsoleSubscriber(), TranscriptLogSubscriber()]
    if os.getenv("MLFLOW_TRACKING_URI"):
        subs.append(MLflowTraceSubscriber(...))
    if os.getenv("DISPATCHER_URL"):
        subs.append(DispatcherEventSubscriber(...))
    elif os.getenv("GITHUB_ACTIONS") == "true":
        subs.append(GHIssueSubscriber(...))
    return subs
```

No mode flag. No config file selects the mode. The runtime environment chooses.

### Domain event model (shared by all modes)

Engine emits the same in-process event stream regardless of mode. Subscribers translate to the appropriate sink.

| Kind | Fields | GH-native translation | Jira-dispatcher translation |
|---|---|---|---|
| `run_started` | `run_id`, `mlflow_url?` | label → `in-progress`, remove `ready`; comment | status → In Progress, comment |
| `stage_started` | `stage` | comment | comment |
| `stage_completed` | `stage`, `ok`, `summary?` | (ok: no-op; !ok: label → `blocked` + comment) | (ok: no-op; !ok: status → Blocked + comment) |
| `pr_opened` | `url`, `base`, `head` | comment (GH auto-links) | comment |
| `pr_updated` | `url`, `kind` | comment | comment; `approved` → In Review |
| `run_completed` | `pr_url?`, `outcome` | label → `in-review` | status → In Review |
| `run_failed` | `error`, `mlflow_url?` | label → `blocked` + comment | status → Blocked + comment |

Unknown kinds are accepted silently by every subscriber (forward compatibility).

### MLflow — first-class, env-gated

`MLflowTraceSubscriber` activates when `MLFLOW_TRACKING_URI` is set. Works in all three modes. Tags every run with:

- `ticket_key` (issue number in Mode 2, Jira key in Mode 1, session_id locally)
- `run_id`
- `branch` (`{ticket_key}/{variant}`)
- `variant` (default `main`)
- `mode` (`local` / `gh-native` / `jira-dispatcher`)

Artifacts uploaded through `--serve-artifacts` proxy mode — no S3 creds in CI. Self-hosted MLflow deployment on Dokploy is documented in a separate ops doc (`docs/ops/self-hosted-mlflow.md`), not in this spec.

## Day 1 — GH-Native Runtime (Mode 2)

### Architecture

```
GH Discussion (requirements thread)
      │
      ▼  (human + shaping skill in CC Desktop)
GH Issues (epic + stories, tasklist-encoded deps)
      │  label "ready" applied to first issue
      ▼
┌───────────────────────────────────────────────────────┐
│  GH Actions — a2sdlc-run.yml                          │
│  trigger: on: issues, types: [labeled]                │
│  if: label.name == 'ready'                            │
│                                                       │
│  uses: yoselabs/a2sdlc-engine/run-native.yml@v1       │
│  env: GITHUB_TOKEN, ANTHROPIC_API_KEY, MLFLOW_*        │
│                                                       │
│  engine:                                              │
│    GHIssueReader → fetch issue body                   │
│    pipeline (SPEC → IMPLEMENT → REVIEW → MERGE)       │
│    GHIssueSubscriber → comments + labels               │
│    MLflowTraceSubscriber (if env set)                  │
│    opens PR with "Closes #N"                          │
└───────────────────────────────────────────────────────┘
      │
      ▼  (PR merged — human or auto-merge)
GH auto-closes issue #N (because "Closes #N")
      │
      ▼
┌───────────────────────────────────────────────────────┐
│  GH Actions — a2sdlc-unblock.yml                      │
│  trigger: on: issues, types: [closed]                 │
│                                                       │
│  step 1: gh api graphql — find all open issues whose  │
│          tasklist contains `- [ ] #N`                 │
│  step 2: for each, check all tasklist deps are closed │
│  step 3: if fully unblocked, add label "ready"        │
│          (which fires a2sdlc-run.yml above)           │
└───────────────────────────────────────────────────────┘
```

### Dependency encoding — GH tasklists

Story issue body includes a native GH tasklist under a known heading:

```markdown
## Description
Implement authentication flow.

## Blocked by
- [ ] #12
- [ ] #14

## Acceptance criteria
- ...
```

GH renders this with progress bars and exposes it via GraphQL `issue.trackedInIssues` / `issue.tasklistReferences`. The unblock workflow parses via `gh api graphql`.

Why tasklists over labels or body conventions: native, robust against issue renames, already supported by GH's own progress UI. Survives copy-paste.

### Label state machine

One label drives the whole lifecycle:

| Label | Meaning | Who sets it |
|---|---|---|
| `ready` | queue for engine | shaping skill (first issue), unblock workflow (subsequent) |
| `in-progress` | engine is working | engine (on `run_started`) |
| `in-review` | PR awaiting merge | engine (on `run_completed`) |
| `blocked` | engine failed | engine (on `run_failed`) |

Engine removes `ready` when it picks up an issue and replaces it with `in-progress`. No race because GH API operations are serialized per-issue.

### Target-repo install

Two workflow files in `.github/workflows/`:

**`a2sdlc-run.yml`**

```yaml
name: a2sdlc — run
on:
  issues:
    types: [labeled]

jobs:
  engine:
    if: github.event.label.name == 'ready'
    uses: yoselabs/a2sdlc-engine/.github/workflows/run-native.yml@v1
    secrets:
      ANTHROPIC_API_KEY:        ${{ secrets.ANTHROPIC_API_KEY }}
      MLFLOW_TRACKING_URI:      ${{ secrets.MLFLOW_TRACKING_URI }}
      MLFLOW_TRACKING_USERNAME: ${{ secrets.MLFLOW_TRACKING_USERNAME }}
      MLFLOW_TRACKING_PASSWORD: ${{ secrets.MLFLOW_TRACKING_PASSWORD }}
```

**`a2sdlc-unblock.yml`**

```yaml
name: a2sdlc — unblock
on:
  issues:
    types: [closed]

jobs:
  unblock:
    uses: yoselabs/a2sdlc-engine/.github/workflows/unblock-native.yml@v1
```

No tracker secrets. No project mapping. `GITHUB_TOKEN` is ambient in Actions.

### Shaping skill — GH mode

Input: GH Discussion or local file.

```
shape-gh <discussion_url | file_path>  [--repo owner/name]
```

1. Read discussion body via `gh api graphql`.
2. Interactive Q&A session (one question per turn), augmenting the draft.
3. Draft a pitch list as markdown with proposed issue titles, bodies, and dependency tasklists.
4. Preview the draft to the user. On approval:
   - `gh issue create` for each story (save the assigned numbers).
   - Second pass: patch each issue body to insert the tasklist with the actual numbers.
   - Add `ready` label to the root (non-blocked) issues.

Out of scope for Day 1: per-pitch design stage, brand/palette, parallel shaping.

### Engine — Day 1 additions

- `packages/engine/src/a2sdlc/adapters/ticket/gh_issue_reader.py` — fetches issue body + metadata via `gh api`.
- `packages/engine/src/a2sdlc/adapters/ticket/gh_issue_subscriber.py` — consumes domain events, calls `gh issue comment` / labels.
- Composition root updates in `cli.py` to add the new branches shown above.

Existing code unchanged.

### Reusable workflows (in engine repo)

- `.github/workflows/run-native.yml` — installs `a2sdlc-engine`, runs the pipeline with Mode 2 env.
- `.github/workflows/unblock-native.yml` — parses tasklists of all open issues that reference the just-closed issue, applies `ready` label to fully-unblocked ones.

### Local eval — unchanged

`a2sdlc run-stage --session <id> --ticket docs/tickets/ABC-1.md <repo>` continues to work. Neither `DISPATCHER_URL` nor `GITHUB_ACTIONS` is set → local composition branch. Subscribers: console + transcript + MLflow (if env set).

## Days 2–3 — Jira Dispatcher (Mode 1)

### Architecture additions

```
Jira ──webhook──► dispatcher (Dokploy)
                     │
                     ▼  workflow_dispatch + inputs
              GH Actions (target repo, Mode 1 workflow)
                     │
                     ▼
         engine → DispatcherEventSubscriber
                 → POST domain events to dispatcher
                 → dispatcher translates → Jira comments / transitions
                     │
                     ▼
                 PR opened → merged → GH webhook → dispatcher
                     │
                     ▼  Jira done + unblock dependents
```

### Dispatcher service — `packages/dispatcher/`

FastAPI. Routes:

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/jira/events` | Jira webhook signature | trigger engine workflow for ready ticket |
| POST | `/gh/events` | GH webhook signature | on PR merge, transition ticket + unblock dependents |
| POST | `/runs/{run_id}/events` | per-run HMAC | ingest domain events from running engine |
| GET | `/healthz` | none | liveness |

### Config — `PROJECTS_JSON` env var

Array of project configs:

```
PROJECTS_JSON=[
  {
    "jira_key": "A2X",
    "repo": "acme/webapp",
    "default_base": "main",
    "status_ready": "Ready",
    "status_in_progress": "In Progress",
    "status_review": "In Review",
    "status_done": "Done",
    "status_blocked": "Blocked"
  }
]
```

Parsed with Pydantic on startup. Hard-fails on malformed input.

Dispatcher-wide secrets (Dokploy env):

```
JIRA_BASE_URL, JIRA_USER, JIRA_TOKEN
GH_APP_ID, GH_APP_PRIVATE_KEY
HMAC_SIGNING_KEY
JIRA_WEBHOOK_SECRET, GH_WEBHOOK_SECRET
DOKPLOY_DEPLOY_TOKEN
```

### Per-run HMAC capability

```
run_hmac = HMAC-SHA256(HMAC_SIGNING_KEY, f"{run_id}|{ticket_key}|{exp}")
token    = base64(f"{run_id}|{ticket_key}|{exp}|{run_hmac}")
```

`exp = now + 24h`. Single-purpose: ingest events for this run. Cannot transition arbitrary tickets.

### Engine — Days 2–3 additions

- `packages/engine/src/a2sdlc/adapters/ticket/workflow_input_reader.py` — reads ticket body + context from workflow inputs.
- `packages/engine/src/a2sdlc/adapters/ticket/dispatcher_event_subscriber.py` — consumes domain events, POSTs to dispatcher.
- Composition root already has the correct env checks from Day 1.

### Target-repo install (Mode 1)

Single workflow file:

```yaml
name: a2sdlc — dispatched
on:
  workflow_dispatch:
    inputs:
      ticket_key:     { required: true, type: string }
      run_id:         { required: true, type: string }
      dispatcher_url: { required: true, type: string }
      run_hmac:       { required: true, type: string }
      base_branch:    { required: false, type: string, default: main }
      ticket_body:    { required: true, type: string }

jobs:
  engine:
    uses: yoselabs/a2sdlc-engine/.github/workflows/run-split.yml@v1
    with:
      ticket_key:     ${{ inputs.ticket_key }}
      run_id:         ${{ inputs.run_id }}
      dispatcher_url: ${{ inputs.dispatcher_url }}
      run_hmac:       ${{ inputs.run_hmac }}
      base_branch:    ${{ inputs.base_branch }}
      ticket_body:    ${{ inputs.ticket_body }}
    secrets:
      ANTHROPIC_API_KEY:        ${{ secrets.ANTHROPIC_API_KEY }}
      MLFLOW_TRACKING_URI:      ${{ secrets.MLFLOW_TRACKING_URI }}
      MLFLOW_TRACKING_USERNAME: ${{ secrets.MLFLOW_TRACKING_USERNAME }}
      MLFLOW_TRACKING_PASSWORD: ${{ secrets.MLFLOW_TRACKING_PASSWORD }}
```

No Jira creds. No mapping file. Tracker body arrives as a workflow input.

### Shaping skill — Jira mode

Input: Confluence page via a2atlassian MCP.

1. Read Confluence page content.
2. Same interactive Q&A loop as GH mode.
3. Draft pitches as markdown preview.
4. On approval:
   - a2atlassian MCP creates Jira epic.
   - Creates stories linked to epic.
   - Adds `is blocked by` links between stories.
   - Transitions the first story to `Ready`.

### Full flow (Mode 1)

1. Shaping skill creates Jira tickets → first → `Ready`.
2. Jira webhook → dispatcher `/jira/events`.
3. Dispatcher looks up `PROJECTS_JSON[A2X]`, mints `run_id` + `run_hmac`, calls `workflow_dispatch` on `acme/webapp` with `ticket_body` in inputs.
4. GH Actions runs the engine with `DISPATCHER_URL` set → `WorkflowInputReader` + `DispatcherEventSubscriber` composed.
5. Engine emits domain events → dispatcher → Jira comments + transitions.
6. Engine opens PR `Closes A2X-42` → `run_completed` → Jira `In Review`.
7. Human merges PR → GH webhook → dispatcher `/gh/events`.
8. Dispatcher transitions `A2X-42` → `Done`. Queries Jira for tickets blocked only by `A2X-42`; transitions those to `Ready`. Each fires step 2.
9. Last ticket in epic → dispatcher calls Dokploy deploy API.

## Optional `.a2sdlc.yml` (per-project preferences)

Applies to all modes. Entirely optional — engine ships defaults.

```yaml
models:
  spec:      claude-opus-4-7
  implement: claude-sonnet-4-6
  review:    claude-opus-4-7

stages: [spec, implement, review, merge]

gates:
  lint:         make lint
  test:         make test
  coverage_min: 80

branches:
  base:   main
  prefix: "{ticket_key}/"

review:
  require_security_pass: true
  auto_merge_on_green:   false
```

Schema-validated at engine startup. Absent file = full defaults.

## Security

- Webhook signatures validated on every `/jira/events` and `/gh/events` request.
- Per-run HMAC scopes event ingestion to a single run and 24h window.
- Target repos hold only `ANTHROPIC_API_KEY` and optional `MLFLOW_*` secrets.
- Dispatcher creds (`JIRA_TOKEN`, `GH_APP_PRIVATE_KEY`, `HMAC_SIGNING_KEY`) live only on Dokploy env.
- Engine in CI cannot call Jira directly — it only speaks to the dispatcher via the domain-event endpoint.
- Engine in GH-native mode uses only `GITHUB_TOKEN`, scoped to the target repo by Actions.

## Observability

- Every engine run = one GH Actions workflow run URL → live logs, steps, timings, re-run button.
- Engine comments the GH Actions run URL and MLflow run URL onto the ticket.
- MLflow captures structured traces, metrics, artifacts, prompt/response pairs — tagged with ticket_key, run_id, branch, variant, mode.
- Dispatcher logs live in Dokploy container logs.

## Scope by milestone

### Day 1 (today) — Mode 2

- uv workspace with `packages/engine/`.
- Adapter split: `TicketInputReader`, `TicketOutputSubscriber`.
- `GHIssueReader`, `GHIssueSubscriber`.
- Composition root env branches for local / GH-native.
- Reusable workflows: `run-native.yml`, `unblock-native.yml`.
- Shaping skill GH mode.
- Docs: onboarding README for target repos.

### Days 2–3 — Mode 1 additive

- `packages/dispatcher/` with FastAPI service.
- `PROJECTS_JSON` config parsing.
- HMAC capability tokens.
- `WorkflowInputReader`, `DispatcherEventSubscriber`.
- Reusable workflow: `run-split.yml`.
- Shaping skill Jira mode (a2atlassian MCP).
- Dokploy compose for dispatcher.
- Dokploy deploy trigger on epic-complete.
- Docker: `Dockerfile.dispatcher`, `Dockerfile.engine` split.

### Deferred (post-demo)

- Parallel A/B variant matrix orchestration (from both Jira trigger and GH label).
- GitLab / Azure Boards adapters.
- Admin UI over `PROJECTS_JSON`.
- Marketplace-published reusable workflows (`yoselabs/a2sdlc-engine@v1` tagged release).
- Per-pitch design / brandbook stage in shaping.
- OIDC token exchange in place of HMAC.
- YAML/SQLite storage for projects (upgrade path from `PROJECTS_JSON`).

## Open Questions

1. **Ticket body size.** Workflow-input size limit is ~1MB. Overflow is unlikely but should gracefully degrade to a dispatcher endpoint (`GET /runs/{run_id}/ticket`). v1: pass as input; track occurrences.
2. **Shaping skill packaging.** Lives in `packages/engine/` under `skills/` for Day 1. Extract later if it gains independent lifecycle.
3. **HMAC expiry duration.** 24h for v1; shorten when refresh flow exists.
4. **Unblock workflow token scope.** Reading tasklists and adding labels needs `issues:write`; `GITHUB_TOKEN` default suffices. No PAT required.

## Invariants (must hold)

- Engine has no Jira-specific code. Jira logic lives exclusively in `packages/dispatcher/`.
- Target repo in either mode has zero persistent tracker credentials.
- Dispatcher never reads or writes target repo code directly.
- MLflow activation is strictly env-gated — unset env = no MLflow code path executed.
- Per-run HMAC is never reused and never exceeds its expiry.
- Local mode is the fallback composition when no ambient runtime signal is set.
- Day 2–3 adds code but does not modify Day 1 engine code paths.
