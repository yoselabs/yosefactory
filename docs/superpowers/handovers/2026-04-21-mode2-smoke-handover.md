# Mode 2 End-to-End Smoke — Outcome

**Date:** 2026-04-21
**Branch:** `feat/mode2-smoke-telemetry`
**Smoke repo:** `iorlas/a2sdlc-smoke` (private, fixture)
**Seed ticket:** `iorlas/a2sdlc-smoke#1` — "Patient intake CLI"
**PR:** `iorlas/a2sdlc-smoke#6` — **merged at 2026-04-21 09:05:02Z**
**MLflow experiment:** `a2sdlc-smoke` on `mlflow.shen.iorlas.net/#/experiments/1`

## TL;DR

Mode 2 is **functional end-to-end** with the fixes landed on this branch. PR #6 merged with 1769 additions / 0 deletions / 20 files — a working, tested `patient-intake` CLI scaffolded from a blank repo by the agent with zero human code edits. The telemetry rewiring (the original goal) proved out against real `mlflow.shen.iorlas.net`: session + stage runs landed with metrics. Several pre-existing engine bugs surfaced during the smoke and have been fixed, workarounded, or filed as follow-ups.

## What worked

| Area | Evidence |
|---|---|
| **Telemetry SSOT + CM/null-object** | `MlflowTelemetry.session(sid)` + `opener.stage(name)` produced nested runs on `mlflow.shen.iorlas.net` experiment id=1. Spec / implement / review stages each emitted child runs with `stage`, `session_id`, `ticket_key`, `target_stage` tags and non-zero metrics. |
| **Subscription auth** | `CLAUDE_CODE_OAUTH_TOKEN` route works — no per-token API billing. The bundled Claude Code CLI in `claude_agent_sdk` accepts OAuth tokens when `ANTHROPIC_API_KEY` is NOT also set (ordering matters). |
| **GitHub App auth** | `actions/create-github-app-token@v3` under `a2sdlc[bot]`. App-origin events DO trigger downstream workflow runs — unblocking the state machine. |
| **Concurrency group + bot-comment filter** | Serialized per-issue; engine's own ✅ comments no longer re-trigger the same stage. Eliminated 2x duplicate runs per stage. |
| **`commit_empty` + push before draft PR** | New `GitAdapter.commit_empty(message)` lets SPEC stage seed the branch with an empty commit so GitHub accepts the draft PR. |
| **Comment quality** | The engine's stage-completion comments are genuinely excellent. Spec comment cited 2 rounds of reviewer Critical/Important fixes; implement comment listed file-by-file deliverables + explicit quality-gate outcomes; both included skill invocations with timestamps and stats (model / cost / tokens / duration / turns). |

### PR #6 — what the agent produced (unedited by human)

```
pyproject.toml
patient_intake/__init__.py
patient_intake/storage.py
patient_intake/cli.py
patient_intake/__main__.py
tests/conftest.py
tests/test_add.py
tests/test_list.py
docs/superpowers/specs/2026-04-21-1-patient-intake-cli.md
docs/superpowers/plans/2026-04-21-1-patient-intake-cli.md
(+ review output.json artifacts)
```

- 6/6 pytest tests pass in the repo.
- Entry point `patient-intake` works via installed script and `python -m patient_intake`.
- Storage uses `PATIENT_INTAKE_DATA_DIR` env override with `platformdirs` fallback — clean separation of production and test sandboxing.
- The agent self-reviewed its spec (2 rounds) and plan (1 minor round) before writing any code.

### Cost (approximate, from stage comment stats)

| Stage | Duration | Tokens in/out | Cost |
|---|---|---|---|
| Spec (final cycle) | 9m 26s | 1k / 24k | $1.14 |
| Implement (final cycle) | 4m 35s | 1k / 12k | $0.71 |
| Review | ~5m | — | ~$0.30 |
| **Ticket total (before cycle thrash)** | — | — | **~$2.15** |

Multiple implement/review cycles ran during state-machine confusion — actual total was ~2–3× the single-pass cost.

## Blockers encountered and fixes

1. **Workflow install path wrong** (`yoselabs/a2sdlc-engine` → `yoselabs/a2sdlc` + `subdirectory=packages/engine`). Commit `340b944`.
2. **`uv tool run a2sdlc`** tries to resolve `a2sdlc` as a PyPI package name. Fixed to call the installed binary directly. Commit `c993501`.
3. **Draft PR creation on empty branch** — 422 "Validation Failed, head invalid". Added `commit_empty` + `push` before `create_draft`. Commit `dd11131`.
4. **Git author identity missing** on runner. Added configure step. Commit `60006cf`.
5. **OAuth token via `ANTHROPIC_API_KEY` fails** — the bundled CLI interprets the token as an API key. Switched to `CLAUDE_CODE_OAUTH_TOKEN` only. Commit `3210478`.
6. **`github.token` anti-loop** — engine's label events didn't fire downstream workflows. Switched to GitHub App token. Commit `7d78cb6` + preflight `30d33dc`.
7. **Engine self-approving PR review** — 422 "Review Can not approve your own pull request". For smoke, human approved manually (iorlas account). Engine still returned verdict=APPROVE correctly in its comment.
8. **Workflow doubling** — engine's ✅ comments re-triggered the workflow. Added bot-author skip `if:` filter. Commit `29b8110`.
9. **No concurrency guard** — rapid events could race. Added per-issue `concurrency:` group. Commit `b640d07`.

## Open issues and follow-ups (see `TODO.md`)

- **Reviewer identity** — self-approval 422 blocks the stage:review → stage:merge transition. Need second App or dedicated service PAT.
- **Mode 2 idempotency** — `cli/dispatch.py` Mode 2 doesn't set `run_id`, so `check_idempotency` never fires. Engine re-ran implement/review in cycles.
- **`agent` label lingers** alongside `stage:*` after transitions.
- **State.json as authoritative** vs label as authoritative. Current design treats label as primary and `state.json` as a cache; should flip this.
- **Structured-log `extra` fields** not rendered by JSON formatter — debugging stage routing is blind without them.
- **Existing-PR reuse** in SPEC stage after partial failure — currently 422s on retry.
- **Engine-side token sniff** for `ghs_` default token — fail loudly.

## State-machine thrash observed

The engine looped spec → implement → review(APPROVE) → implement → review(REQUEST_CHANGES) → implement during the session. Root causes:
1. Human approval (iorlas) fired `pull_request_review:submitted` → engine's feedback routing interpreted it as "new review iteration needed".
2. Engine's own `stage:*` label writes didn't auto-advance because of the self-approval 422, so I cycled labels manually — each manual cycle fired fresh events that overlapped with queued runs.
3. No idempotency in Mode 2 → each event executed the full stage again.

The concurrency group added mid-session cancelled most duplicate queued runs, but stages already in flight ran to completion.

## Phase 2 readiness

Dispatcher + Jira (Phase 2 of the spec) is **not yet ready**. Prerequisites:
- Reviewer-identity follow-up must land — Jira runs won't have a human in the loop to manually approve.
- Idempotency follow-up must land — Jira webhook redelivery would cause duplicate runs otherwise.
- Stale workflow fixes should be merged to `main` and the `@feat/mode2-smoke-telemetry` pin reset to `@main`.

## Merge-to-main checklist

Before merging `feat/mode2-smoke-telemetry` to `main`:

- [ ] Replace `@feat/mode2-smoke-telemetry` with `@main` in `.github/workflows/run-native.yml:40` (engine install URL) and `.github/workflows/run-split.yml:72`.
- [ ] Confirm 120+ commits don't include temp debug code. `git log --oneline main..HEAD` shows only the intentional changes.
- [ ] Keep TODO.md follow-ups as they describe real work.
