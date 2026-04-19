# Jira Dispatcher — Handover (mid-execution)

**Date:** 2026-04-19
**Branch:** `feat/jira-dispatcher`, HEAD `a457062`
**Next task:** B-2.1 (JiraClient with corrected JQL) — was about to dispatch a subagent when the session ended.

## What's done

### Plan A — GH-native runtime (SHIPPED to local `main` at `b7a5b5a`, NOT pushed)

6 commits fast-forwarded into `main`:

| SHA | Scope |
|---|---|
| `bb2d2c7` | uv workspace refactor — engine moved to `packages/engine/src/a2sdlc/`, workspace root pyproject, 6 import-linter contracts preserved |
| `6bc2141` | `.github/workflows/run-native.yml` reusable workflow for Mode 2 |
| `a5a3446` | `.github/workflows/unblock-next.yml` — GraphQL `trackedInIssues` / `trackedIssues` tasklist unblocker |
| `81f5c44` | `docs/mode2/example-workflows/a2sdlc-run.yml` + `a2sdlc-unblock.yml` — target repo copy-paste |
| `74719b1` | `skills/shaping-gh/` — SKILL.md + pitch template + create-issues.sh |
| `b7a5b5a` | `docs/mode2/README.md` — Mode 2 onboarding guide |

Task 1.2 was **skipped** — engine already had `set_stage_label`, `set_done_label`, `set_blocked` on the `WorkAdapter` protocol, wired in `pipeline/dispatch.py`.

Task 3.2 (smoke test on a throwaway repo) was **not executed** — manual validation requiring a real repo + secrets; left as pending user action.

`main` is **90 commits ahead of `origin/main`** (84 prior unpushed + 6 Day-1 commits). Not pushed per user request.

### Plan B — Jira dispatcher (in progress on `feat/jira-dispatcher`)

5 commits so far:

| SHA | Task | Scope |
|---|---|---|
| `cc4e2f8` | B-0.3 | Scaffolded `packages/dispatcher/` — pyproject.toml, `server.py` with `/healthz`, `__init__.py`, `_version.py`, `tests/__init__.py`. Dependencies: fastapi>=0.115, uvicorn, httpx, pydantic>=2.8, pydantic-settings, atlassian-python-api, pyjwt[crypto], python-ulid. |
| `3d61bf2` | B-1.1 | `domain_events.py` — discriminated union of 7 known event kinds (`run_started`, `stage_started`, `stage_completed`, `pr_opened`, `pr_updated`, `run_completed`, `run_failed`) + `UnknownEvent` fallback. 6 tests. |
| `37086b0` | B-1.2 | `hmac_token.py` — `mint_token`, `verify_token`, `TokenError`, `TokenClaims` dataclass. 4 tests. **Note:** subagent made a minor correct deviation — raises `TokenError("bad signature")` when base64 tampering causes `UnicodeDecodeError`, because the test contract expects tampered tokens to be reported as signature failures regardless of corruption level. |
| `028a163` | B-1.3 | `settings.py` — `ProjectConfig` (Pydantic) + `Settings` (BaseSettings) with `PROJECTS_JSON` alias, `self_url`, `gh_app_installation_id` fields. 3 tests. |
| `a457062` | B-1.4 | `runs_table.py` — thread-safe `RunsTable` with `register`/`get`/`finish`/`active_run_for` + `mark_in_progress_sent` / `has_in_progress_been_sent` (the In-Progress dedupe flag). 5 tests. |

**All 5 phase-1 tests pass. `make check` green at `a457062`.**

## What's next — immediate

B-2.1 is next. A partial `test_jira_client.py` was created during the interrupted run but has been deleted so pre-commit's `ty` hook stops failing on unresolved imports. Re-run B-2.1 from scratch using the plan spec (Task 2.1 in `docs/superpowers/plans/2026-04-19-jira-dispatcher.md`).

## Remaining Plan B tasks (in execution order)

| # | ID | Scope | Status |
|---|---|---|---|
| 19 | B-2.1 | JiraClient with corrected JQL (linkedIssues, not "is blocked by" =) | in_progress (partial test file) |
| 20 | B-2.2 | Event → Jira translator with per-run In-Progress dedupe | pending |
| 21 | B-3.1 | Webhook signature helpers (`verify_github_sig`, `verify_jira_sig`) | pending |
| 22 | B-3.2 | GHAppClient with lazy JWT-based installation token refresh (5-min margin) | pending |
| 23 | B-3.3 | POST `/jira/events` — trigger workflow_dispatch, pass `ticket_body` from webhook (ADF flatten), use `SELF_URL` env | pending |
| 24 | B-3.4 | POST `/runs/{run_id}/events` — HMAC bearer auth, route to translator | pending |
| 25 | B-3.5 | POST `/gh/events` — PR merged → transition Done → unblock dependents | pending |
| 26 | B-4.1 | Engine adapter: `WorkflowInputReader` — env-driven input; write methods as no-op sentinels | pending |
| 27 | B-4.2 | Engine adapter: `DispatcherEventSubscriber` — POSTs `stage_started`/`stage_completed`; NO `run_started` emission | pending |
| 28 | B-4.3 | CLI wiring: guard `GitHubWorkAdapter` + `GhCommentSubscriber` behind `if not dispatcher_url` | pending |
| 29 | B-5.1 | `.github/workflows/run-split.yml` + target-repo example | pending |
| 30 | B-6.1 | `skills/shaping-jira/` scaffold (via a2atlassian MCP) | pending |
| 31 | B-7.1 | `Dockerfile.engine` | pending |
| 32 | B-7.2 | `Dockerfile.dispatcher` | pending |
| 33 | B-7.3 | Dokploy compose + runbook (with `GH_APP_INSTALLATION_ID`, `SELF_URL` env; no long-lived `GH_INSTALLATION_TOKEN`) | pending |
| 34 | B-8.1 | `docs/mode1/README.md` onboarding guide | pending |
| 35 | B-8.3 | Final gate + fast-forward merge into main | pending |

Smoke test (B-8.2) is deferred (manual, needs real Jira + deployed dispatcher).

## Key artifacts to read at session start

1. **Plan B** — `docs/superpowers/plans/2026-04-19-jira-dispatcher.md` (post-review fixes committed in `dd0aeea`). This is the source of truth for task specs.
2. **Design spec** — `docs/superpowers/specs/2026-04-19-shaping-and-dispatcher-design.md` (revision 2). Architecture + invariants.
3. **Plan A** — `docs/superpowers/plans/2026-04-19-gh-native-runtime.md`. Done, but useful for cross-reference.

## Critical invariants (don't regress)

1. **Engine never emits `run_started`.** The dispatcher dedupes `Ready → In Progress` on first `stage_started` per `run_id` via `RunsTable.mark_in_progress_sent`. Plan B Task 4.2 must enforce this.
2. **JQL uses `linkedIssues(KEY, "blocks")`.** NOT `"is blocked by" = KEY` — that syntax is invalid. Plan B Task 2.1 locks this.
3. **WorkflowInputReader write methods are no-ops returning sentinels**, NOT `NotImplementedError`. Otherwise CommentManager in the engine's normal path crashes. Plan B Task 4.1.
4. **CLI wiring guards `GitHubWorkAdapter`**. In dispatcher mode (`DISPATCHER_URL` set), don't construct it — it would require `GITHUB_REPOSITORY` + PyGithub auth that may not be valid. Plan B Task 4.3.
5. **HMAC tokens are per-run capabilities, 24h expiry.** No refresh; mint fresh per run. Plan B Task 1.2 (done).
6. **`dispatcher_url` in workflow inputs comes from `SELF_URL` env on dispatcher, not `request.base_url`.** Traefik rewriting makes the latter unreliable. Plan B Task 3.3.

## Execution style

User prefers the **subagent-driven-development** skill flow:
- Dispatch one subagent per task (general-purpose, model=sonnet).
- Give subagent the full spec + code blocks inline (not "read the plan file").
- TDD order: failing test first, verify fail, implement, verify pass, commit.
- Between tasks: I (controller) verify the commit, update TaskUpdate, move on.
- HEREDOC commits with trailer `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- Pre-commit hooks (`auto-fix` + `agent-harness lint`) run automatically; if they reformat, re-stage and proceed.

## Commands for orientation

```bash
# Confirm where we are
git -C /Users/iorlas/Workspaces/a2sdlc-engine branch --show-current
# expected: feat/jira-dispatcher

git -C /Users/iorlas/Workspaces/a2sdlc-engine log --oneline main..HEAD
# expected: a457062, 028a163, 37086b0, 3d61bf2, cc4e2f8

# Verify tests still pass
cd /Users/iorlas/Workspaces/a2sdlc-engine && make check

# Show pending untracked
git -C /Users/iorlas/Workspaces/a2sdlc-engine status
# expected: packages/dispatcher/tests/test_jira_client.py untracked
```

## Known gotchas

- Local `main` is 90 commits ahead of `origin/main`. Not pushed. Plan B PR (when ready) merges locally into `main`; push is explicit user call.
- `pytest-asyncio` is installed workspace-wide; `asyncio_mode = "auto"` is NOT set in pyproject. If a future test uses async and fails without the marker, add `@pytest.mark.asyncio` per test or add the global config to root `pyproject.toml`'s `[tool.pytest.ini_options]`.
- Security audit reports 3 dependency advisories (cryptography, pytest, python-multipart). Pre-existing, warnings not failures. Leave for a separate cleanup pass.
- `ty` (type checker) uses `# ty: ignore[<rule>]` syntax, not `# type: ignore`. B-1.3 subagent applied `# ty: ignore[missing-argument]` on `Settings()` test callsites — follow same pattern for new Pydantic BaseSettings callsites that tell `ty` fields are env-injected.

## Open scope notes (not today's problem)

- The partial `test_jira_client.py` is stub — only 52 lines, cuts off mid-test. Re-run B-2.1 to regenerate (easier than patching mid-file).
- `test_gh_app.py` in the plan expects `asyncio_mode = "auto"` or explicit `@pytest.mark.asyncio` decorators. Plan already has the decorators, so this should just work.
- When `server.py` wires in the Jira routes, it needs to construct `JiraClient` via `atlassian.Jira(...)` — use lazy construction (defer to first request) if startup-time network calls to Jira are undesirable in local dev.
