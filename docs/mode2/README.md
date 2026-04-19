# a2sdlc — GitHub-only runtime (Mode 2)

Drop two workflow files into your target repo and the engine will drive
tickets through SPEC → IMPLEMENT → REVIEW → MERGE on GitHub Actions, using
GH Issues as the tracker.

## What you need

- A GitHub repo with Issues enabled.
- Secrets configured in the repo:
  - `ANTHROPIC_API_KEY` (required)
  - `MLFLOW_TRACKING_URI` + `MLFLOW_TRACKING_USERNAME` + `MLFLOW_TRACKING_PASSWORD` (optional; skip if you don't want telemetry)

## Install

1. Copy `example-workflows/a2sdlc-run.yml` → `.github/workflows/a2sdlc-run.yml`.
2. Copy `example-workflows/a2sdlc-unblock.yml` → `.github/workflows/a2sdlc-unblock.yml`.
3. Commit, push.

That's it. No other files, no mappings, no per-repo config.

## Drive it

### Manual (single-ticket mode)

1. Create a GH Issue with a description.
2. Apply the `agent` label.
3. Watch the Actions tab: the engine runs SPEC → IMPLEMENT → REVIEW → MERGE
   across four workflow runs (one per stage), advancing via `stage:*` labels.
4. On completion the engine opens a PR with `Closes #<issue>`. Human merges.
5. Issue auto-closes. If other issues reference this one under `## Blocked by`,
   they'll get the `agent` label automatically and the cycle repeats.

### Batch (shaping mode)

Use the `shaping-gh` skill (see `skills/shaping-gh/SKILL.md`) to turn a GH
Discussion or brief into a pre-ordered graph of issues in one go.

## Label state machine

| Label          | Meaning                                              | Who sets it                                   |
|----------------|------------------------------------------------------|-----------------------------------------------|
| `agent`        | kick off SPEC stage                                  | you (or shaping skill, or unblock workflow)   |
| `stage:spec`   | SPEC in progress                                     | engine                                        |
| `stage:implement` | IMPLEMENT in progress                             | engine                                        |
| `stage:review` | REVIEW in progress                                   | engine                                        |
| `stage:merge`  | MERGE stage opening PR                               | engine                                        |
| `stage:done`   | fully done                                           | engine                                        |
| `stage:blocked`| engine failed — inspect comments                     | engine                                        |
| `needs-input`  | engine asked a question, awaiting human reply        | engine                                        |
| `proceed`      | human answered `needs-input`, resume                 | human                                         |

## Dependency encoding (for multi-ticket features)

In a story's issue body, include a section exactly named `## Blocked by`
containing GitHub task-list items referencing blockers:

```markdown
## Blocked by
- [ ] #12
- [ ] #14
```

When #12 and #14 close, the `unblock-next` workflow applies the `agent` label
to this issue automatically.

## Observability

- **GH Actions**: every engine run is a workflow run URL — logs, steps, re-run.
- **MLflow** (optional): if secrets set, every run is tagged with
  `ticket_key`, `run_id`, `branch`, `variant`, `mode`.
- **Issue comments**: the engine posts throttled status updates via
  `GhCommentSubscriber`.

## Troubleshooting

| Symptom                                     | Likely cause                                        |
|---------------------------------------------|-----------------------------------------------------|
| Nothing runs after labelling `agent`        | Check Actions tab; secret `ANTHROPIC_API_KEY` unset |
| Engine loops on SPEC                        | Stage-transition label writes missing (Task 1.2)    |
| Unblock workflow doesn't trigger dependents | `## Blocked by` header mistyped or mixed casing     |
| MLflow empty                                | Optional secrets unset; engine runs without it      |
