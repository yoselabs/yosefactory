# Resume Prompt — Mode 2 Smoke Follow-Ups

> **Paste this verbatim into a fresh session to pick up the work.** It assumes the new agent has no prior context.

---

## Where we are

You're picking up after a successful Mode 2 end-to-end smoke test of the `a2sdlc` engine against `iorlas/a2sdlc-smoke` (private fixture repo) and `mlflow.shen.iorlas.net`. The telemetry rewiring (Phase 1 of the plan at `docs/superpowers/plans/2026-04-21-mode2-e2e-smoke.md`) landed, `make check` is green, 531 tests pass under xdist in ~12s, and the smoke produced PR #6 which was merged.

Branch: **`feat/mode2-smoke-telemetry`** (120+ commits ahead of `main`, pushed to origin). Everything you need is there.

**Required reads before doing anything (in order):**
1. `docs/superpowers/handovers/2026-04-21-mode2-smoke-handover.md` — outcome summary, all 9 fixes, all 7 follow-ups.
2. `docs/superpowers/specs/2026-04-21-mode2-e2e-smoke-design.md` — design intent.
3. `TODO.md` sections "Mode 2 auth/trigger follow-ups" and "Test infrastructure follow-ups".

Do not re-do any work already in the handover's "What worked" table.

## Environment facts (do not re-discover)

- Engine repo: `yoselabs/a2sdlc` (NOT `yoselabs/a2sdlc-engine` — that's the historical name, now wrong everywhere).
- Engine package lives at `packages/engine/` in a uv workspace monorepo.
- Smoke repo: `iorlas/a2sdlc-smoke` — private. `a2sdlc[bot]` GitHub App is installed on it.
- Smoke repo secrets already set: `A2SDLC_APP_ID`, `A2SDLC_APP_PRIVATE_KEY`, `A2SDLC_INSTALLATION_ID`, `CLAUDE_CODE_OAUTH_TOKEN`, `MLFLOW_TRACKING_URI`, `MLFLOW_TRACKING_USERNAME`, `MLFLOW_TRACKING_PASSWORD`. Ignore the stale `ANTHROPIC_API_KEY` and `A2SDLC_BOT_TOKEN` secrets — they're no longer used.
- Queued ticket `iorlas/a2sdlc-smoke#2` is unlabeled — exercises "extend existing code". Label `agent` to run when ready.
- Test suite uses pytest-xdist. `make test` = ~12s pytest + coverage. `make check` = lint + arch + tests + coverage-diff + security-audit.

## Next-priority follow-ups (from `TODO.md`)

### 1. Reviewer identity (HIGH — blocks Phase 2 / Jira)
Engine's review stage tries to self-approve its own PR using the `a2sdlc[bot]` App token → GitHub returns `422 Review Can not approve your own pull request`. Three viable options:
- **(a) Second "reviewer" GitHub App** with approval scope only.
- **(b) Dedicated service-account PAT** stored as a separate secret.
- **(c) Skip the PR review API call in Mode 2** and transition `stage:merge` label directly based on engine verdict, trusting the engine's own judgment. Cheapest; loses the GitHub-native approval artifact.

Recommendation: option (c) for Phase 2 (Jira has no equivalent of GH PR review anyway). Document the tradeoff.

### 2. Mode 2 idempotency (HIGH — blocks Phase 2)
`cli/dispatch.py` Mode 2 branch doesn't set `ctx.run_id`. `StateManager.check_idempotency` is gated on `ctx.run_id`, so Mode 2 re-executes stages on every event. Derive run_id from `f"{event.key}:{target_stage.value}:{git_head_sha}"` or similar and pass it into `DispatchContext`. Tests at `tests/pipeline/` should cover.

### 3. State.json as authoritative (MEDIUM)
Current: GH label is primary state, `state.json` is a cache. This invites races when users/engines cycle labels concurrently. Flip the contract — label is a display artifact; `state.json` on the branch is the source of truth; transitions commit+push `state.json` first, label update is a best-effort mirror.

### 4. Structured-log `extra` fields (LOW — but BIG debugging win)
`cli/dispatch.py:setup_logging` JSON formatter drops `extra={}` kwargs on `logger.info(...)` calls. During this smoke, debugging stage routing was blind because `target_stage`, `trigger_stage`, `is_feedback` are all logged via `extra={...}` and silently discarded. Update the formatter to include extras in the JSON output.

### 5. Agent-label cleanup (LOW)
`agent` label should be removed when the engine transitions to any `stage:*`. Currently lingers cosmetically.

### 6. Existing-PR reuse (LOW)
`GitHubReviewAdapter.create_draft_pr` should look up existing PR by `head=branch` before calling `create_pull` — avoids 422 on retry after partial failure.

### 7. Engine token sniff (LOW)
`cli/dispatch.py` should detect a `ghs_`-prefixed `GITHUB_TOKEN` and refuse to run with a clear error. The GHA default token silently breaks the state machine without this check.

## Merge-to-main checklist

Before merging `feat/mode2-smoke-telemetry` to `main`:

1. **Un-pin workflow refs** — change `@feat/mode2-smoke-telemetry` back to `@main`:
   - `.github/workflows/run-native.yml:40` (engine install URL)
   - `.github/workflows/run-split.yml:72` (engine install URL)
   - Consumer repos' `a2sdlc-run.yml` — none currently pinned; the pinning in `iorlas/a2sdlc-smoke/.github/workflows/a2sdlc-run.yml` was smoke-specific and can be reset when you want.
2. `make check` clean (should be — last run was green).
3. Squash or cherry-pick? This branch has ~130 commits including many incremental workflow fixes. If squashing, consider grouping: Telemetry (Tasks 1-10), Parallel tests, Workflow fixes, Smoke handover. If cherry-picking, each commit is already well-scoped.
4. After merge, smoke repo can optionally be cleaned: `gh repo delete iorlas/a2sdlc-smoke --confirm` — or kept as a permanent smoke fixture.

## Do not do

- Don't re-run the smoke to "verify" — it's done. Budget respected.
- Don't switch back to `ANTHROPIC_API_KEY` — the OAuth token path is working and free (subscription billing).
- Don't set `ANTHROPIC_API_KEY` alongside `CLAUDE_CODE_OAUTH_TOKEN` — the CLI prefers API key and it'll fail.
- Don't fall back to `github.token` — the preflight in `run-native.yml` hard-fails on that now, which is correct.
- Don't add `@pytest.mark.serial` to any test without a one-line justification comment.

## If you need to run the smoke again

```bash
# From a fresh clone of yoselabs/a2sdlc on feat/mode2-smoke-telemetry branch
make check                             # sanity
# Re-open the smoke — open issue #2 or create a new one with an `agent` label
gh issue edit <N> --repo iorlas/a2sdlc-smoke --add-label agent
# Watch via the monitor pattern in the handover
```

Expect: the `a2sdlc[bot]` App generates a token, draft PR opens, spec → implement → review runs, review stage fails at self-approval (known follow-up #1), human merge needed.
