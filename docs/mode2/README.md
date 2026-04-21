# a2sdlc — GitHub-only runtime (Mode 2)

Drop two workflow files into your target repo and the engine drives
GitHub Issues through SPEC → IMPLEMENT → REVIEW → MERGE on GitHub
Actions. No external dispatcher, no extra services.

## 1. Secrets

Set these in the target repo (Settings → Secrets and variables → Actions):

| Secret | Required | Purpose |
|---|---|---|
| `A2SDLC_APP_ID` | ✅ | GitHub App ID — the engine authors commits/PRs as this App. |
| `A2SDLC_APP_PRIVATE_KEY` | ✅ | App private key (full PEM). |
| `CLAUDE_CODE_OAUTH_TOKEN` | ✅ | Token for Claude Agent SDK calls. |
| `MLFLOW_TRACKING_URI` | optional | MLflow server URI; if unset, engine runs without telemetry. |
| `MLFLOW_TRACKING_USERNAME` | optional | MLflow basic-auth user. |
| `MLFLOW_TRACKING_PASSWORD` | optional | MLflow basic-auth password. |

The GitHub App must be installed on the target repo. Installation ID is
resolved automatically by `actions/create-github-app-token@v3` — no
`A2SDLC_INSTALLATION_ID` secret needed.

## 2. GitHub App permissions

The `a2sdlc` GitHub App needs these repository permissions:

- **Contents**: Read & write (push branches, commit handovers)
- **Issues**: Read & write (comment, label, close)
- **Pull requests**: Read & write (open, update, review)
- **Metadata**: Read (standard)

Event subscriptions: Issues, Issue comment, Pull request, Pull request
review, Pull request review comment.

## 3. Install the workflows

Copy these two files into the target repo:

```
docs/mode2/example-workflows/a2sdlc-run.yml     → .github/workflows/a2sdlc-run.yml
docs/mode2/example-workflows/a2sdlc-unblock.yml → .github/workflows/a2sdlc-unblock.yml
```

Commit, push. No other per-repo config is required unless you want to
override gates (see §5).

**Important: the issues trigger must include `closed`.** When the
engine's auto-merge (or a human) closes an issue, the engine handles
that event by stripping `stage:*` and `agent` labels off the closed
ticket. Without the `closed` subscription those labels linger on the
board even though the work is done. The shipped example already has it.

## 4. Drive a ticket

1. Open a GitHub Issue with a clear description.
2. Apply the `agent` label.
3. Watch the Actions tab — the engine runs SPEC → IMPLEMENT → REVIEW →
   MERGE, one workflow run per stage. The ticket comment stream shows
   progress live.
4. On APPROVE, the engine merges (or hands off to a human — see §5).
5. When the PR merges, the issue auto-closes. Dependents (issues that
   reference this one under `## Blocked by`) get the `agent` label via
   `a2sdlc-unblock.yml`.

## 5. Gate modes — HUMAN vs AUTO merge

The engine's merge stage has two modes, controlled by
`.a2sdlc/config.yaml`:

```yaml
gates:
  merge: human    # default — engine opens PR, waits for human merge
  # merge: auto   # engine merges on its own APPROVE verdict
```

| Mode | Who merges | When to use |
|---|---|---|
| `human` (default) | You (via GitHub UI) | Production repos, repos with branch protection requiring reviews, open-source repos. Respects `CODEOWNERS` and GitHub's review requirements. |
| `auto` | The engine (on its own APPROVE review) | Trusted-internal repos, spike/smoke repos, fully-agentic automation. Bypasses branch protection human-review gates — the engine's verdict *is* the decision. |

**AUTO caveat.** The App that authors the PR cannot submit an APPROVE
review on its own PR (GitHub returns 422). The engine treats this
silently: the stage comment on the issue carries the engine's verdict,
and AUTO mode merges without a PR review. If branch protection requires
a review, AUTO won't satisfy it — use HUMAN instead, or grant the App's
team review-bypass.

**Per-ticket override.** A ticket body can override the gate for that
ticket alone:

```
gate_spec: auto
base: develop
```

## 6. Dependency encoding

Multi-ticket features can encode dependencies in the issue body:

```markdown
## Blocked by
- [ ] #12
- [ ] #14
```

When #12 and #14 close, `a2sdlc-unblock.yml` applies the `agent` label
to this issue automatically.

## 7. Observability

- **GitHub Actions** — every engine run is a workflow-run URL. Logs,
  steps, re-run.
- **Issue comments** — the engine posts throttled progress updates
  directly on the ticket. On failure, a `Blocked:` comment points at
  the failing workflow run.
- **MLflow** (optional) — if `MLFLOW_TRACKING_URI` is set, every run
  creates a parent session tagged with `ticket_key`, `run_id`, `mode`;
  each stage is a nested child run with `tokens_in`, `tokens_out`,
  `cost_usd`, `stage`, `verdict`.

## 8. Label state machine

| Label | Meaning | Who sets it |
|---|---|---|
| `agent` | kick off (or resume via unblock workflow) | you / shaping skill / unblock workflow |
| `stage:spec` | SPEC running | engine |
| `stage:implement` | IMPLEMENT running | engine |
| `stage:review` | REVIEW running | engine |
| `stage:merge` | MERGE running | engine |
| `stage:blocked` | engine hit an error — inspect comments | engine |
| `needs-input` | engine asked a question, awaiting human reply | engine |
| `proceed` | human answered `needs-input`, resume | human |

The `stage:done` label was removed in 2026-04 — closed-issue state is
now the done signal (matches Jira's native "Done" status).

## 9. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Nothing runs after labelling `agent` | Required secrets unset, or App not installed on the repo. Check Actions tab for workflow startup errors. |
| Engine self-cancels on merge APPROVE | Expected under AUTO mode — App can't APPROVE its own PR. Engine merges anyway via the stage comment's verdict. |
| Unblock workflow doesn't trigger dependents | `## Blocked by` header mistyped or casing differs — it's matched exactly. |
| `stage:*` / `agent` labels linger on a closed issue | Workflow's `issues:` trigger missing `closed` — see §3. |
| MLflow empty | Optional secrets unset; engine runs without MLflow. |
| Engine re-runs same stage on every event | Idempotency relies on `ctx.run_id`; check that the workflow forwards `GITHUB_RUN_ID` (the shipped example does). |
