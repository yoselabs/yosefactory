# Mode 2 End-to-End Smoke Test — Design

**Date:** 2026-04-21
**Status:** Design approved, pending implementation plan
**Scope:** One session. Phase 2 (Jira + dispatcher) is a separate spec.

## Goal

Prove a2sdlc Mode 2 (GitHub-native, no dispatcher) end-to-end on a fresh private repo with MLflow observability. Confirm the full spec → implement → review → merge state machine reaches quiescence on a realistic-but-small ticket, and that every stage emits MLflow telemetry against `mlflow.shen.iorlas.net`.

## Non-Goals

- No dispatcher deployment. Mode 2 does not use it.
- No Jira integration. Separate phase, separate spec.
- No yoselabs org. Throwaway repo under `iorlas/`.
- No multi-ticket batch test. One ticket end-to-end.
- No auto-merge. Human clicks "Merge" on the PR.

## Architecture

Mode 2 reference: `docs/mode2/README.md`. All orchestration lives inside the target repo's GitHub Actions; the engine is invoked as a reusable workflow (`yoselabs/a2sdlc-engine/.github/workflows/run-native.yml@main`). One outbound HTTPS call per stage to MLflow; otherwise GitHub-only.

```
iorlas/a2sdlc-smoke (private)
├── .github/workflows/a2sdlc-run.yml   # verbatim from docs/mode2/example-workflows/
└── README.md                          # one-liner purpose

Issue opened + `agent` label
          │
          ▼
   GHA run-native.yml
          │
          ├── stage:spec      → posts spec comment on issue → stage:implement
          ├── stage:implement → pushes commits to a branch  → stage:review
          ├── stage:review    → posts review verdict         → stage:merge
          └── stage:merge     → opens PR with `Closes #N`    → HUMAN GATE
                                                                   │
                                                                   ▼
                                                            manual git merge via UI
```

Telemetry: each stage invocation streams to `mlflow.shen.iorlas.net` under experiment `a2sdlc-smoke`, parent run `session:<sid>`, child runs `<sid>:<stage>`. Implementation already in place — see `packages/engine/src/a2sdlc/evaluation/mlflow_sink.py` and `packages/engine/src/a2sdlc/cli/run_stage.py:130`.

## Repo Setup

1. Create private repo `iorlas/a2sdlc-smoke` via `gh repo create`.
2. Commit only:
   - `.github/workflows/a2sdlc-run.yml` — copy of `docs/mode2/example-workflows/a2sdlc-run.yml` verbatim.
   - `README.md` — single line describing this as a smoke-test fixture for a2sdlc.
3. Labels: engine creates `stage:*` on demand. No pre-seeding.
4. Repo permissions (`Settings → Actions → General`):
   - Workflow permissions: **Read and write**.
   - **Allow GitHub Actions to create and approve pull requests** — required for the review stage.

## Secrets

Set via `gh secret set` on the target repo. Never committed.

| Secret | Source |
|---|---|
| `ANTHROPIC_API_KEY` | rotated key (post this session, treat any key shared in chat as compromised) |
| `MLFLOW_TRACKING_URI` | `https://mlflow.shen.iorlas.net` |
| `MLFLOW_TRACKING_USERNAME` | `ci` |
| `MLFLOW_TRACKING_PASSWORD` | rotated value |

MLflow SDK reads the username/password env vars natively; no URI-embedded basic auth.

## Seed Ticket

**Title:** `Patient intake CLI`

**Body (Gherkin):**

```gherkin
Feature: Patient intake
  Scenario: Add a patient
    When I run `patient-intake add --name "Ada Lovelace" --dob 1815-12-10 --complaint "headache"`
    Then a record is persisted
    And `patient-intake list` prints it in a table
```

**Kickoff:** human applies the `agent` label on the issue (per `docs/mode2/README.md`). The engine takes it from there; all `stage:*` labels are engine-owned. This is the only human action until the pre-merge gate.

## Observation Checklist

Each transition must be observed in order. If any stage reaches `stage:blocked`, stop and triage before rerunning.

1. `agent` label applied → GHA `dispatch` job fires → engine posts spec comment → label flips from `agent` to `stage:implement` (via the engine's own `stage:spec` transient).
2. `stage:implement` → engine pushes commits to a feature branch → label flips to `stage:review`.
3. `stage:review` → engine posts review verdict (on issue today; PR-posting is an open TODO) → on approval, label flips to `stage:merge`.
4. `stage:merge` → engine opens the PR with `Closes #<issue>` → **STOP for human gate**.
5. **Human pre-merge gate:** inspect PR diff, confirm tests green in CI, confirm MLflow captured the run (see below). Only then click "Merge pull request" in the GitHub UI.
6. Post-merge: repo must be quiescent — no additional workflow runs should fire.

## MLflow Verification

Log in to `mlflow.shen.iorlas.net` with the `ci` credentials. Expect:

- Experiment `a2sdlc-smoke` exists.
- One parent run `session:<sid>`.
- Child runs for at least `spec`, `implement`, `review` — named `<sid>:<stage>`.
- Each child tagged with `stage` and `session_id`; non-zero metrics (duration, cost, turns).
- `merge` stage MLflow emission is **unverified** in current code. If absent, file a follow-up; not a blocker for smoke success.

## Success Criteria

- Issue reaches `stage:merge` without hitting `stage:blocked`.
- PR contains a runnable `patient-intake` CLI plus passing pytest. Code quality can be rough; correctness and test pass are the bar.
- MLflow shows the nested session/stage structure described above.
- Human merge completes cleanly. Post-merge state is quiescent.

## Known Failure Modes

- **Bootstrap confusion:** blank repo forces the agent to choose a Python toolchain. Watch the spec stage for this; if the agent picks something odd, it's signal for the prompt layer, not a smoke-test failure.
- **MLflow auth:** `MlflowSink.verify_reachable()` raises `MlflowUnreachableError` early. Any such error in stage logs points to secret wiring, not the engine.
- **Label races:** Mode 2 depends on label ordering. Simultaneous events on the same issue could produce duplicate stage invocations. Rare; noted.
- **Self-approving review:** review stage currently approves its own PR. Accepted for smoke. Must be addressed (separate reviewer identity) before Jira phase.

## Phase 2 Preview

Out of scope for this spec. After smoke succeeds:

1. Deploy dispatcher to shen (Dokploy compose already staged in `deploy/dokploy/`).
2. Create a second private repo wired to Jira via dispatcher `workflow_dispatch`.
3. Re-run the same seed-ticket shape, triggered by a Jira issue.

Phase 2 gets its own spec and plan when we get there.
