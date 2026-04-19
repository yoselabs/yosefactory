# a2sdlc — Jira + GitHub runtime (Mode 1)

End-to-end: Confluence requirements → shaping skill → Jira epic + stories
linked by "is blocked by" → dispatcher fires engine in your repo's GH
Actions → PR opens → human merges → dispatcher transitions Jira and
unblocks the next story.

## What you install

### In the dispatcher (Dokploy)

See `deploy/dokploy/README.md`.

### In each target repo

1. Copy `docs/mode1/example-workflows/a2sdlc-split.yml` →
   `.github/workflows/a2sdlc-split.yml`.
2. Repo secrets:
   - `ANTHROPIC_API_KEY` (required)
   - `MLFLOW_*` (optional)
3. Ensure the yoselabs GitHub App is installed on this repo with
   `actions: write`, `contents: write`, `pull_requests: write`.

No Jira creds in the repo. No mapping file.

## Driving it

1. In Claude Code Desktop, invoke the `shaping-jira` skill against a
   Confluence page or brief.
2. Skill creates an epic + stories with "is blocked by" links, transitions
   the root story to `Ready`.
3. Dispatcher receives Jira webhook, triggers `a2sdlc-split.yml` on the
   target repo with `run_id` + `run_hmac` + `ticket_body` in the inputs.
4. Engine runs SPEC → IMPLEMENT → REVIEW → MERGE, posting progress events
   to the dispatcher, which comments/transitions Jira.
5. Engine opens PR with `Closes JIRA-KEY`.
6. You merge the PR. GitHub webhook → dispatcher → Jira ticket → Done.
7. Dispatcher transitions any fully-unblocked dependents to `Ready`. Cycle
   repeats until the epic is complete.

## Observability

- Jira ticket comments with the GH Actions run URL and (if MLflow set)
  MLflow run URL.
- GH Actions run page — live logs, re-run button.
- MLflow — structured trace per run, tagged with `ticket_key`, `run_id`,
  `branch`, `variant`, `mode=jira-dispatcher`.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Jira ticket sits in Ready, no workflow fires | Webhook URL wrong; webhook secret mismatch; `JIRA_WEBHOOK_SECRET` env unset on dispatcher |
| Workflow fires but Jira isn't updated | `DISPATCHER_URL` not passed into workflow; `RUN_HMAC` mismatch (regenerate) |
| PR merges but dependents stuck Blocked | `Closes <KEY>` missing from PR body; issue links not `is blocked by` |
| Dispatcher 401 on `/runs/{id}/events` | Token expired (>24h) or wrong signing key |
