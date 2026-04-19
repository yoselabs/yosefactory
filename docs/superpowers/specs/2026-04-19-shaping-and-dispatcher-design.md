# Shaping & Dispatcher — Design

**Date:** 2026-04-19
**Status:** Draft, pending user review
**Revision:** 1

## Problem

Today a2sdlc is a per-ticket pipeline (SPEC → IMPLEMENT → REVIEW → MERGE). Two layers are missing to demo the full SDLC story end-to-end:

1. **Requirements → tickets.** There is no interactive shaping layer that turns vague requirements into a dependency-ordered set of tickets. Humans author tickets manually today.
2. **Ticket orchestration.** No component watches the tracker to launch pipeline runs for newly-unblocked tickets, nor to transition tickets when a PR merges.

We need both layers to show a client demo in 4 days: vague requirements in Confluence → interactive shaping → Jira epic + stories → agents pick up unblocked tickets → PRs → merges unblock next → final app deployed. The solution must be the real foundation, not throwaway glue.

## Goals

1. **End-to-end automation from "ticket is ready" to "PR is merged" to "next ticket is ready."** No manual intervention between shaping and deploy.
2. **Engine stays ticket-system-agnostic.** Engine emits domain events; no new Jira awareness inside the engine.
3. **Target-repo install footprint is a single workflow file.** No secrets, no per-repo mappings.
4. **Adapters already in the engine stay there.** Dispatcher is not a duplicate adapter layer; it is the remote end of one specific adapter (`DispatcherClient`).
5. **One config store.** Routing/credentials live in the dispatcher deployment only. Per-project preferences live in the target repo. No duplication.
6. **Mode is ambient, not declared.** Engine picks its adapters from environment signals — no `--mode` flag, no dotfile mode switch.
7. **MLflow is optional.** Engine runs fine without it. If env vars are set, telemetry subscriber activates.

## Non-Goals (v1)

- Multi-tracker clients (Jira + Linear at the same deployment). One tracker per dispatcher for now.
- GitLab / Azure Boards / ClickUp adapters. Follow-up.
- Native GH-issues mode (Mode 2) as a shipped runtime. Architecture supports it; we don't build it in v1.
- Shared MLflow across dispatchers, dashboards, or eval comparison UI.
- Parallel A/B variant runs triggered by the dispatcher. The engine supports variants via `branches.prefix`; orchestrated A/B is follow-up.
- Replacing or generalizing `config/projects.yaml` with a UI. (Edit via Dokploy env/volume.)
- Retry policies, dead-letter queues, crash recovery for in-flight runs. First failure is surfaced; re-run is manual.
- OIDC / token-exchange auth. HMAC capability tokens are the v1 mechanism.

## Architecture

Three components in the final picture:

```
              ┌───────────────────────────── Dokploy host ─────────────────────────┐
              │                                                                    │
              │  ┌──────────────────────────────────────────┐                      │
              │  │  dispatcher  (tiny FastAPI service)      │                      │
              │  │                                          │                      │
              │  │  POST /jira/events                       │                      │
              │  │  POST /gh/events                         │                      │
              │  │  POST /runs/{run_id}/events (HMAC)       │                      │
              │  │                                          │                      │
              │  │  config/projects.yaml                    │                      │
              │  │  env: JIRA_TOKEN, GH_APP_PRIVATE_KEY,    │                      │
              │  │       HMAC_SIGNING_KEY                   │                      │
              │  └──────────────────────────────────────────┘                      │
              │                                                                    │
              │  ┌──────────────────────────────────────────┐                      │
              │  │  mlflow (optional)                        │                      │
              │  │  basic-auth + serve-artifacts            │                      │
              │  └──────────────────────────────────────────┘                      │
              └────┬────────────────────────────────────────┬──────────────────────┘
                   ▲                                        │
     webhooks (Jira, GitHub)                   workflow_dispatch + per-run inputs
                   │                                        ▼
           ┌───────────────┐                     ┌───────────────────────────────────┐
           │  Jira, GitHub │                     │  GH Actions in target repo        │
           └───────────────┘                     │                                   │
                                                 │  uses: yoselabs/a2sdlc-engine      │
                                                 │                                   │
                                                 │  engine runs pipeline             │
                                                 │    → DispatcherClient adapter      │
                                                 │      POSTs domain events          │
                                                 │    → Code adapter opens PR        │
                                                 │    → MLflowTraceSubscriber         │
                                                 │      (if MLFLOW_TRACKING_URI set)  │
                                                 └───────────────────────────────────┘
```

### Component responsibilities

**Shaping (Claude Code Desktop + skills + MCP).** Human-driven, interactive. Output = Jira epic with linked stories. Not a service, not part of the engine.

**Dispatcher (new).** Thin FastAPI service on Dokploy. Three jobs:
1. Receive tracker webhooks, decide whether to trigger engine runs.
2. Ingest domain events from running engine jobs (authenticated via per-run HMAC) and translate them into tracker actions (comments, status transitions).
3. Receive code-host webhooks (PR merged), transition the corresponding ticket to Done, and unblock dependents.

**Engine (existing, minor additions).** Gains two new adapters and an env-driven composition root. Pipeline stages unchanged.

## Shaping Flow (Option C: hybrid with approval gate)

Owned by the human, not the engine. Documented here so the whole story holds together.

### Inputs

The shaping skill accepts three input kinds:

| Scheme | Backing | Used in |
|---|---|---|
| `confluence://<space>/<page-id>` | a2atlassian MCP | Jira-tracker projects |
| `github://discussions/<repo>/<number>` | `gh api graphql` | GH-native projects |
| `file://<path>` | local filesystem | local experiments / standalone |

All three normalize into raw text that the skill consumes.

### Interaction

1. Load the input document.
2. Ask the user clarifying questions one at a time (project scope, audience, constraints, success criteria).
3. Draft a pitch list (Shape Up style — appetite, problem, solution sketch, dependencies).
4. Present the draft as a reviewable artifact (markdown block in Claude Code Desktop + proposed diff to the Confluence page).
5. After user approval, commit to the tracker:
   - Create an epic for the milestone.
   - Create a story per pitch, linked to the epic.
   - Add `is blocked by` links between stories to encode the intended order.
   - First story transitions to `Ready`. Remaining stories stay in `Blocked`.

### Why Option C

- Nothing lands in Jira until the user types "ship it." Safe even if the session derailed.
- The pitch-list artifact is reviewable and editable as plain markdown.
- The Confluence page retains the living doc; Jira stories link back to it for traceability.

### Out of scope for v1

- Automatic brand/palette/design stage per pitch.
- Parallel-agent shaping (multiple agents proposing pitch slices).
- Reading input from private sources other than Confluence / Discussions / file.

## Dispatcher Service

### HTTP surface

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/jira/events` | Jira webhook secret | Ticket transitioned to Ready → maybe trigger workflow |
| POST | `/gh/events` | GitHub webhook secret (or GH App signature) | PR merged → transition ticket + unblock dependents |
| POST | `/runs/{run_id}/events` | per-run HMAC (bearer) | Ingest domain events from a running engine job |
| GET | `/healthz` | none | liveness |

No other endpoints. No arbitrary Jira passthrough — only domain events.

### Config (`config/projects.yaml`)

Single YAML file, shipped in the image or mounted from Dokploy volume/env.

```yaml
projects:
  A2X:
    ticket_source: jira
    code_host: github
    repo: acme/webapp
    default_base: main
    jira_ready_status: "Ready"
    jira_in_progress_status: "In Progress"
    jira_review_status: "In Review"
    jira_done_status: "Done"
    jira_blocked_status: "Blocked"
```

### Secrets (Dokploy env)

- `JIRA_BASE_URL`, `JIRA_USER`, `JIRA_TOKEN`
- `GH_APP_ID`, `GH_APP_PRIVATE_KEY` (preferred) or `GH_PAT`
- `HMAC_SIGNING_KEY` (random 32 bytes, per-deployment)
- `DOKPLOY_DEPLOY_TOKEN` (for final-milestone deploy trigger)
- Optional: `JIRA_WEBHOOK_SECRET`, `GH_WEBHOOK_SECRET`

### Per-run HMAC capability token

When the dispatcher triggers a workflow, it mints an HMAC signing a `(run_id, ticket_key, exp)` tuple:

```
run_hmac = HMAC-SHA256(HMAC_SIGNING_KEY, f"{run_id}|{ticket_key}|{exp}")
token    = base64(f"{run_id}|{ticket_key}|{exp}|{run_hmac}")
```

Passed to the workflow as a `workflow_dispatch` input. The engine attaches it to every `/runs/{run_id}/events` request. The dispatcher validates HMAC + expiry on ingestion. `exp` is `now + 24h` — long enough for the longest pipeline run, short enough to bound misuse.

This token is a narrow capability: it can only ingest events for this run. It cannot transition arbitrary tickets, cannot read Jira, cannot call GitHub.

### Trigger flow (Jira → workflow_dispatch)

1. Jira webhook arrives on `/jira/events`.
2. Dispatcher extracts ticket key (e.g. `A2X-42`) and verifies payload signature.
3. Lookup `projects[A2X]` for repo + adapter settings.
4. Confirm ticket status == `Ready` and all `is blocked by` links resolve to `Done`. If not, ignore (defence-in-depth).
5. Check no active run already exists for this ticket (MLflow query by `tags.jira_key='A2X-42' AND status='RUNNING'`, or a simple in-memory lock).
6. Mint `run_id` (ULID) and `run_hmac`.
7. Call GitHub REST `POST /repos/acme/webapp/actions/workflows/a2sdlc.yml/dispatches` with inputs:

    ```json
    {
      "ref": "main",
      "inputs": {
        "ticket_key": "A2X-42",
        "run_id": "01H...",
        "dispatcher_url": "https://dispatcher.yose.tld",
        "run_hmac": "…",
        "base_branch": "main"
      }
    }
    ```

8. Record the run intent locally (small in-memory map `run_id → ticket_key`) so `/runs/{run_id}/events` can route.

### PR-merged flow (GitHub → Jira unblock)

1. GitHub PR-merged webhook arrives on `/gh/events`.
2. Parse PR body for `Closes <KEY>` (or fall back to branch-name prefix match).
3. Transition `<KEY>` to `Done`.
4. Query Jira: `jql=project=<proj> AND status=Blocked AND "is blocked by" = <KEY>`.
5. For each candidate, verify *all* its blockers are now Done.
6. Transition those to `Ready`. Each transition fires a Jira webhook → back to the trigger flow.
7. If no more tickets remain in the milestone's epic, call Dokploy deploy API.

### Event ingest flow (`/runs/{run_id}/events`)

Engine POSTs a domain event, e.g.

```json
{ "kind": "stage_started", "stage": "implement" }
```

Dispatcher resolves `run_id → ticket_key`, validates HMAC, and dispatches to the tracker adapter:

```python
ticket_source.apply(ticket_key, event)
```

Adapter (`jira_adapter.py`) has a finite `match` statement translating event kinds into comments + transitions. Unknown event kinds are logged but do not fail the request.

## Engine Changes

### New adapters

Both under `adapters/ticket/`:

- **`dispatcher_client.py`** — `TicketAdapter` implementation that emits domain events over HTTP to `{DISPATCHER_URL}/runs/{RUN_ID}/events`, authed by `{RUN_HMAC}`. Does not know Jira.
- **`github_native.py`** (follow-up, not v1) — `TicketAdapter` that reads/writes GH issues via `gh` CLI. Listed here for completeness; not implemented in v1.

### Subscriber

- **`dispatcher_event_subscriber.py`** — listens to the existing subscriber event stream, translates to the domain-event HTTP contract, POSTs via `dispatcher_client`. Mirror of `gh_comment_subscriber.py`.

### Env-driven composition root

Location: engine entry point (extends existing `cli.py` / `cli_local.py`). Adds a branch for split-brain CI context:

```python
def build_ticket_adapter() -> TicketAdapter:
    if os.getenv("DISPATCHER_URL"):
        return DispatcherClient(
            url=os.environ["DISPATCHER_URL"],
            run_id=os.environ["RUN_ID"],
            hmac=os.environ["RUN_HMAC"],
        )
    if os.getenv("GITHUB_ACTIONS") == "true" and os.getenv("GITHUB_EVENT_NAME") == "issues":
        return GitHubNative(token=os.environ["GITHUB_TOKEN"])  # follow-up, not v1
    return LocalFile(...)  # existing local runner behaviour

def build_subscribers() -> list[Subscriber]:
    subs = [ConsoleSubscriber(), TranscriptLogSubscriber()]
    if os.getenv("DISPATCHER_URL"):
        subs.append(DispatcherEventSubscriber(...))
    if os.getenv("MLFLOW_TRACKING_URI"):
        subs.append(MLflowTraceSubscriber(...))
    return subs
```

No mode flag anywhere. No dotfile mode switch. Engine reads its environment.

### Domain event contract (v1)

Event kinds the engine emits via `DispatcherEventSubscriber`:

| Kind | Fields | Dispatcher → Jira translation |
|---|---|---|
| `run_started` | `run_id`, `mlflow_url?` | status → In Progress, comment "Run started" |
| `stage_started` | `stage` | comment "Entering stage: <stage>" |
| `stage_completed` | `stage`, `ok`, `summary?` | (no-op on ok; on !ok, status → Blocked + comment with summary) |
| `pr_opened` | `url`, `base`, `head` | comment with PR link |
| `pr_updated` | `url`, `kind` (ci-green / changes-requested / approved) | comment; on approved status → In Review |
| `run_completed` | `pr_url?`, `outcome` | on success: leave In Review for merge; on failure: → Blocked with error |
| `run_failed` | `error`, `mlflow_url?` | status → Blocked, comment with error + MLflow link |

Unknown event kinds MUST be accepted by `/runs/{run_id}/events` and logged — the engine may add new kinds ahead of dispatcher awareness. The dispatcher's `match` statement ignores unknown kinds.

### What does not change

- `stages/*` — unchanged.
- `pipeline/dispatch.py` — unchanged.
- `domain/` — unchanged.
- `assembly/`, `lifecycle/`, `evaluation/` — unchanged.
- Existing adapters (`github.py`, `git.py`, `work.py`, `review.py`, existing subscribers) — unchanged.

## Target Repo Contract

### Required: one workflow file

`.github/workflows/a2sdlc.yml`:

```yaml
name: a2sdlc

on:
  workflow_dispatch:
    inputs:
      ticket_key:     { required: true,  type: string }
      run_id:         { required: true,  type: string }
      dispatcher_url: { required: true,  type: string }
      run_hmac:       { required: true,  type: string }
      base_branch:    { required: false, type: string, default: main }

jobs:
  engine:
    uses: yoselabs/a2sdlc-engine/.github/workflows/run-split.yml@v1
    with:
      ticket_key:     ${{ inputs.ticket_key }}
      run_id:         ${{ inputs.run_id }}
      dispatcher_url: ${{ inputs.dispatcher_url }}
      run_hmac:       ${{ inputs.run_hmac }}
      base_branch:    ${{ inputs.base_branch }}
    secrets:
      MLFLOW_TRACKING_URI:      ${{ secrets.MLFLOW_TRACKING_URI }}      # optional
      MLFLOW_TRACKING_USERNAME: ${{ secrets.MLFLOW_TRACKING_USERNAME }} # optional
      MLFLOW_TRACKING_PASSWORD: ${{ secrets.MLFLOW_TRACKING_PASSWORD }} # optional
      ANTHROPIC_API_KEY:        ${{ secrets.ANTHROPIC_API_KEY }}
```

No Jira creds, no GH PAT beyond the default `GITHUB_TOKEN`, no project mapping.

### Optional: `.a2sdlc.yml` for project preferences

```yaml
models:
  spec:      claude-opus-4-7
  implement: claude-sonnet-4-6
  review:    claude-opus-4-7

stages: [spec, implement, review, merge]

gates:
  lint:     make lint
  test:     make test
  coverage_min: 80

branches:
  base:   main
  prefix: "{ticket_key}/"

review:
  require_security_pass: true
  auto_merge_on_green: false
```

Engine ships defaults for every field; the dotfile is purely for overrides. Engine schema-validates on startup.

## End-to-End Trace (Jira mode)

1. Human opens CC Desktop, invokes shaping skill against `confluence://ACME/12345`.
2. Skill asks questions; human answers. Skill drafts pitch list; human approves.
3. Skill writes Jira: epic `A2X-40`, stories `A2X-41..A2X-45` with blocker chain. `A2X-41` → `Ready`, rest → `Blocked`.
4. Jira fires webhook to `https://dispatcher.yose.tld/jira/events`.
5. Dispatcher validates, looks up `projects[A2X] = acme/webapp`, mints `run_id=01H...` + `run_hmac`, calls GitHub `workflow_dispatch`.
6. `acme/webapp`'s `a2sdlc.yml` workflow starts. Reusable workflow `yoselabs/a2sdlc-engine/run-split.yml` runs the engine.
7. Engine composition root reads `DISPATCHER_URL` → installs `DispatcherClient` + `DispatcherEventSubscriber`; reads `MLFLOW_TRACKING_URI` → installs `MLflowTraceSubscriber`.
8. Engine emits `run_started` → POST to dispatcher → Jira status → `In Progress`, comment with MLflow link.
9. Pipeline runs. Each stage emits `stage_started` / `stage_completed` events; dispatcher comments on Jira.
10. Pipeline's MERGE stage calls the code adapter → opens PR against `main`. `pr_opened` event → Jira comment with PR URL.
11. Engine emits `run_completed(outcome=awaiting_merge)`. Workflow exits 0.
12. Human (or auto-merge on green) merges the PR.
13. GitHub fires PR-merged webhook to `/gh/events`.
14. Dispatcher parses `Closes A2X-41`, transitions `A2X-41` → `Done`, queries Jira for newly unblocked tickets, transitions `A2X-42` → `Ready`.
15. Back to step 4 for `A2X-42`.
16. When the last story in epic `A2X-40` transitions to `Done`, dispatcher calls Dokploy deploy API.

## Security

- **Webhook endpoints** verify Jira / GitHub signatures.
- **Per-run HMAC** scopes the engine's event ingestion to a single run and expires in 24h. Cannot be replayed for other tickets.
- **Target repo has no persistent tracker secrets.** Only `ANTHROPIC_API_KEY` and optional `MLFLOW_*` live in its secrets.
- **Dispatcher creds** live only on Dokploy env. Rotation = update env + redeploy.
- **TLS** terminated at Traefik on Dokploy host.
- **Engine in CI cannot read from Jira.** Dispatcher pushes the ticket body and any user answers into the workflow inputs or the engine's prompt context as needed. (If richer context is required, add specific fields to the `workflow_dispatch` inputs or a signed one-shot `GET /runs/{run_id}/ticket` endpoint. v1 passes the minimum.)

## Observability

- Every engine run = one GH Actions workflow run → logs, steps, duration, re-run button come for free.
- Dispatcher posts `Running: <gh-actions-run-url>` to the Jira ticket at `run_started` — the live URL is the observability UI.
- MLflow (optional) captures structured metrics, artifacts, and prompt/response traces. Tagged with `jira_key`, `run_id`, `branch`, `variant`.
- Dispatcher logs retained per Dokploy container defaults.

## Deployment (Dispatcher on Dokploy)

Single compose service + Traefik labels + optional MLflow sibling service (see `docs/ops/self-hosted-mlflow.md`, separate from this spec).

```yaml
services:
  dispatcher:
    image: ghcr.io/yoselabs/a2sdlc-dispatcher:v1
    environment:
      JIRA_BASE_URL: ${JIRA_BASE_URL}
      JIRA_TOKEN:    ${JIRA_TOKEN}
      GH_APP_ID:     ${GH_APP_ID}
      GH_APP_PRIVATE_KEY: ${GH_APP_PRIVATE_KEY}
      HMAC_SIGNING_KEY:   ${HMAC_SIGNING_KEY}
      DOKPLOY_DEPLOY_TOKEN: ${DOKPLOY_DEPLOY_TOKEN}
    volumes:
      - ./projects.yaml:/app/config/projects.yaml:ro
    labels:
      traefik.enable: "true"
      traefik.http.routers.dispatcher.rule: "Host(`dispatcher.yose.tld`)"
      traefik.http.routers.dispatcher.tls.certresolver: cloudflare
```

## Demo Scope (4-day client demo)

**In scope:**

- Shaping skill (Confluence input, Jira output, option-C UX).
- Dispatcher service (Jira + GitHub, one project).
- Engine `DispatcherClient` adapter + `DispatcherEventSubscriber`.
- Reusable workflow `run-split.yml` in the engine repo.
- Target repo setup: `.github/workflows/a2sdlc.yml` + optional `.a2sdlc.yml`.
- MLflow optional subscriber (env-gated).
- Final-milestone Dokploy deploy trigger.

**Deferred:**

- GitHub-native mode runtime (architecture supports it; no shipped code in v1).
- GitLab adapter.
- A/B parallel runs via workflow matrix.
- UI over `projects.yaml`.
- Per-pitch design / brandbook stage.
- Multi-tracker deployment.
- Automated retry / dead-letter queue.

## Open Questions

1. **Ticket body access in CI.** The engine needs the ticket description. Options: (a) dispatcher passes `ticket_body` as a workflow input; (b) engine calls `GET /runs/{run_id}/ticket` on the dispatcher. Recommend (a) for v1 — zero extra endpoints; watch for 1MB workflow-input size limit.
2. **Jira custom field for MLflow link.** Nice-to-have. If not wanted, MLflow URL goes in a comment only.
3. **Concurrency policy.** One run per ticket at a time (enforced by the dispatcher). Engine-level concurrency across tickets is capped by GH Actions concurrency keys — default unset (parallel).
4. **HMAC expiry tradeoff.** 24h is long. Shorter expiry requires refresh, more code. Pick 24h for v1.
5. **Shaping skill packaging.** Part of `a2sdlc-engine` repo under `skills/`, or a separate `yoselabs/shaping-skill` repo? v1: in engine repo for now; extract later.

## Invariants (must hold)

- Engine has no Jira-specific code in CI-loaded modules. Only `dispatcher_client.py` and `dispatcher_event_subscriber.py` are aware of the dispatcher's existence, and neither knows what a ticket system is.
- Target repo has no secrets or mappings beyond what is listed in the workflow file above.
- Dispatcher never reads or writes target repo code.
- MLflow is optional at every layer — if env unset, no MLflow code path is executed.
- Per-run HMAC is never reused and never exceeds its expiry.

## Follow-ups (post-demo)

- Mode 2 (GH-native) runtime: implement `github_native.py` adapter + `run-native.yml` reusable workflow + issue-labeled trigger. Ships as the "install one action" OSS pitch.
- GitLab adapter pair (`gitlab_native.py` + GitLab webhook on the dispatcher).
- Per-pitch design stage in shaping (optional brand/palette generation).
- A/B variant orchestration via GH Actions `strategy.matrix`.
- Dispatcher Jira-proxy mode for the rare Mode 3 case where CI must not hold MLflow creds.
- Promote `projects.yaml` + `run_id → ticket_key` map to SQLite when the engine gains multi-dispatcher deployments or a UI.
