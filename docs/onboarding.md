# a2sdlc Onboarding — 5-minute install

From zero to first agent-driven PR. **If this takes more than 5 minutes of human effort, file an issue — the adoption gate (product vision P-08) has been violated.**

Target: GitHub-hosted repo. GitLab and Jira paths at the bottom.

---

## 1. Install two GitHub Apps

Both Apps live in a single GitHub organization. You install them on the repo you want a2sdlc to manage.

| App | Purpose | Scopes |
|---|---|---|
| `a2sdlc-worker` | Opens PRs, commits, labels, merges after approval | `contents:write`, `issues:write`, `pull_requests:write` |
| `a2sdlc-reviewer` | Reviews and approves PRs (distinct GitHub identity — counts under branch protection) | `contents:read`, `pull_requests:write` |

Install links: *(to be filled in when Apps are published)*

Both Apps installed → **step done**.

## 2. Add repo secrets

Settings → Secrets and variables → Actions → New repository secret.

| Secret | Required | Value |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | yes | Your Anthropic token for the agent runner |
| `MLFLOW_TRACKING_URI` | optional | Any MLflow server URL (local file store used if unset) |

`GITHUB_TOKEN` is auto-provided by Actions. The two installed Apps authenticate independently via their installation keys — no additional token secrets needed.

## 3. Drop in the workflow file

Copy `templates/workflow-ci-edition.yml` to your repo at `.github/workflows/a2sdlc.yml`. Do not modify.

## 4. Drop in the config file

Create `.a2sdlc/config.yaml`:

```yaml
workflow: default     # see docs/workflows/ for alternatives
default_base: main
```

This is the minimal config. The `default` workflow is opinionated: SPEC → IMPLEMENT → REVIEW → MERGE, Claude Sonnet for all stages, human gate on merge.

Want to customize? See `docs/workflows/` for declarative examples (skill sets, prompts, per-stage models, subagents, transitions). No engine code changes required — all experiments are YAML.

## 5. Label an issue `agent`

Open any issue. Click Labels → `agent`. A CI job fires; the engine takes over.

**The issue will update with a progress comment within ~30 seconds.**

---

## What if it doesn't work?

- CI job didn't start → check that both Apps are installed and that `.github/workflows/a2sdlc.yml` was committed.
- CI job started but failed on auth → check that both App installation IDs are present in Settings → GitHub Apps.
- Progress comment shows "rate_limited" → check `rate_limited_until` on the ticket; a scheduled sweep will re-dispatch when the window clears (see architecture vision §2.23).
- PR opened but can't merge due to branch protection → engine falls back to "PR ready, awaiting human merge" (see Q12). This is expected behavior.

## GitLab

Equivalent steps with two Project Access Tokens (Reporter+Approver for reviewer, Developer for worker). Full GitLab onboarding: `docs/onboarding-gitlab.md` (TBD when GitLab adapter ships).

## Jira

Jira requires the Mode 1 dispatcher service (hosted separately, one per organization). Full Jira onboarding: `docs/onboarding-jira.md` (TBD).

---

## Keeping this under 5 minutes

If a new feature proposal would add a sixth step to the checklist above, the default answer is **no**. The proposer must either:
- Fold the step into an existing one, OR
- Make the step opt-in (not required for the happy path), OR
- Demonstrate that the team gains more than 5 minutes of value from adding the step.

This is product principle P-08 in `docs/vision/01-product-vision.md`.
