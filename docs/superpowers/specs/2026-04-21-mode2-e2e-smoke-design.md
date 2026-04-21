# Mode 2 End-to-End Smoke Test — Design

**Date:** 2026-04-21
**Status:** Design approved, pending implementation plan
**Scope:** One session. Phase 2 (Jira + dispatcher) is a separate spec.

## Goal

Prove a2sdlc Mode 2 (GitHub-native, no dispatcher) end-to-end on a fresh private repo with MLflow observability against `mlflow.shen.iorlas.net`. Confirm the full spec → implement → review → merge state machine reaches quiescence on a realistic-but-small ticket, and that every stage emits MLflow telemetry.

Observability today is broken in CI: both `.github/workflows/run-native.yml` (Mode 2) and `.github/workflows/run-split.yml` (Mode 1) invoke `a2sdlc dispatch`, and `cli/dispatch.py` contains **zero** MLflow wiring. Secrets are forwarded through the workflows but silently dropped by the engine. `cli/run_stage.py` has MLflow wiring but hardcodes `file://~/.a2sdlc/mlflow`, ignoring `MLFLOW_TRACKING_URI`. This spec includes the prerequisite rewiring so the smoke run produces real telemetry.

## Non-Goals

- No dispatcher deployment. Mode 2 does not use it.
- No Jira integration. Separate phase, separate spec.
- No yoselabs org. Throwaway repo under `iorlas/`.
- No multi-ticket batch test. One ticket end-to-end.
- No auto-merge. Human clicks "Merge" on the PR.
- No OpenTelemetry / alternate backend. MLflow only this round (but the chosen abstraction makes a future OTel backend a drop-in).

## Prerequisite — Telemetry wiring (must land before smoke run)

The root cause of the observability gap is that every CLI entry point makes its own telemetry decisions. Fix once, at the evaluation layer, using a Python-native context-manager + null-object combination so call sites are branch-free and new entry points get telemetry for free.

### Abstractions

A new module `packages/engine/src/a2sdlc/evaluation/telemetry.py` exposes:

```python
class Telemetry(Protocol):
    @contextmanager
    def session(self, session_id: str) -> Iterator[StageOpener]: ...
    @property
    def traces_enabled(self) -> bool: ...   # whether to attach MlflowTraceSubscriber

class StageOpener(Protocol):
    @contextmanager
    def stage(self, name: str) -> Iterator[RunHandle]: ...

class RunHandle(Protocol):
    def log_metric(self, key: str, value: float) -> None: ...
    def log_tag(self, key: str, value: str) -> None: ...
    def log_dict(self, data: dict, path: str) -> None: ...

class MlflowTelemetry:  # wraps today's MlflowSink
    ...

class NoopTelemetry:    # null object — every method is a no-op, traces_enabled=False
    ...

def telemetry_from_env(experiment_name: str) -> Telemetry:
    """SSOT. The only place that reads MLFLOW_TRACKING_URI."""
    uri = os.environ.get("MLFLOW_TRACKING_URI")
    if not uri:
        return NoopTelemetry()
    t = MlflowTelemetry(tracking_uri=uri, experiment_name=experiment_name)
    t.verify_reachable()  # fail fast — do not silently degrade on bad creds
    return t
```

### Call-site shape (identical for `cli/dispatch.py` and `cli/run_stage.py`)

```python
telemetry = telemetry_from_env(experiment_name=project_root.name)
with telemetry.session(session_id) as opener, opener.stage(stage.value) as run:
    run.log_tag("git_sha_before", sha_before)
    result = await dispatch(ctx)
    if result.stats:
        run.log_metric("cost_usd", result.stats.cost_usd)
        # ...
```

No `if sink is None` branches. No MLflow imports in the CLI layer.

### Trace subscriber wiring

`build_progress_state(...)` in `assembly/wire.py` accepts the `Telemetry` instance (or a `traces_enabled: bool`) and registers `MlflowTraceSubscriber` only when the real backend is active. Null object → no subscriber.

### Backward compatibility

- `cli/run_stage.py` preserves today's local-dev UX: if `MLFLOW_TRACKING_URI` is unset **and** `--no-track` is not passed, fall back to `file://~/.a2sdlc/mlflow`. This is a local-only branch inside `run_stage.py` (not in the shared factory), kept for developer ergonomics.
- `--no-track` in `run_stage.py` continues to bypass telemetry entirely (passes `NoopTelemetry()` explicitly).
- `cli/dispatch.py` has no local fallback: env set → remote; env unset → null.

### Tests

- Unit: `telemetry_from_env` returns `NoopTelemetry` unset, `MlflowTelemetry` set, raises `MlflowUnreachableError` on bad URI.
- Unit: `NoopTelemetry` session/stage context managers are safe no-ops; `traces_enabled is False`.
- Integration: `cli/dispatch.py` given `MLFLOW_TRACKING_URI=file://tmp` produces a run on disk with expected experiment/session/stage naming and metric keys.
- Regression: existing `tests/evaluation/test_mlflow_sink.py` migrated to `MlflowTelemetry` surface; behavior unchanged.

### Docs

- `docs/local-runner-usage.md` — note the `MLFLOW_TRACKING_URI` env override; default remains local file store.
- `README.md:48` — same.
- `docs/mode2/README.md` — already correct; no change.

## Architecture (smoke test)

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

Telemetry: each stage invocation streams to `mlflow.shen.iorlas.net`. Experiment name = `project_root.name`, which equals the checked-out repo directory name on GHA (`a2sdlc-smoke`). Parent run `session:<sid>`, child runs `<sid>:<stage>`.

## Repo Setup

1. Create private repo `iorlas/a2sdlc-smoke` via `gh repo create`.
2. Commit only:
   - `.github/workflows/a2sdlc-run.yml` — copy of `docs/mode2/example-workflows/a2sdlc-run.yml` verbatim.
   - `README.md` — single line describing this as a smoke-test fixture for a2sdlc.
3. Labels: engine creates `stage:*` on demand. No pre-seeding.
4. Repo permissions (`Settings → Actions → General`):
   - Workflow permissions: **Read and write**. Covers PR creation during merge stage and review posting during review stage (the reusable workflow declares `pull-requests: write`).
   - **Allow GitHub Actions to create and approve pull requests** — required specifically for the review stage to approve its own PR.
5. **Branch protection on `main`:** confirm *no* rule requiring an external reviewer. Default for a fresh private repo is no protection, but org policy could inject one — verify before the run, else the merge stage's PR will be blocked from approval and the human merge will also be blocked.

## Secrets

Set via `gh secret set` on the target repo. Never committed.

| Secret | Source |
|---|---|
| `ANTHROPIC_API_KEY` | rotated key (any key shared in chat is treated as compromised and must be rotated) |
| `MLFLOW_TRACKING_URI` | `https://mlflow.shen.iorlas.net` |
| `MLFLOW_TRACKING_USERNAME` | `ci` |
| `MLFLOW_TRACKING_PASSWORD` | rotated value |

MLflow SDK reads the username/password env vars natively; no URI-embedded basic auth.

## Seed Ticket

**Title:** `Patient intake CLI`

**Body (Gherkin):**

```gherkin
Feature: Patient intake
  Scenario: Add and list patients
    Given no patients are stored
    When I run `patient-intake add --name "Ada Lovelace" --dob 1815-12-10 --complaint "headache"`
    Then a record is persisted
    When I run `patient-intake list`
    Then the output contains "Ada Lovelace" in a table
```

**Kickoff:** human applies the `agent` label on the issue (per `docs/mode2/README.md`). The engine takes it from there; all `stage:*` labels are engine-owned. This is the only human action until the pre-merge gate.

## Observation Checklist

Each transition must be observed in order. If any stage reaches `stage:blocked`, stop and triage before rerunning.

1. `agent` label applied → GHA `dispatch` job fires → engine posts spec comment → `agent` removed, `stage:implement` added. Verify `stage:spec` transient is cleared, not just added-then-left.
2. `stage:implement` → engine pushes commits to a feature branch → label flips to `stage:review`.
3. `stage:review` → engine posts review verdict (on issue today; PR-posting is an open TODO) → on approval, label flips to `stage:merge`.
4. `stage:merge` → engine opens the PR with `Closes #<issue>` → **STOP for human gate**.
5. **Human pre-merge gate:** inspect PR diff, confirm tests green in CI, confirm MLflow captured the run (see below). Only then click "Merge pull request" in the GitHub UI.
6. Post-merge: repo must be quiescent — no additional workflow runs should fire. Note: `a2sdlc-unblock.yml` is intentionally NOT installed in this smoke (no dependent issues exist). This is a known omission vs. the Mode 2 bundled workflows.

## MLflow Verification

Log in to `mlflow.shen.iorlas.net` with the `ci` credentials. Expect:

- Experiment `a2sdlc-smoke` exists.
- One parent run `session:<sid>`.
- Child runs for at least `spec`, `implement`, `review` — named `<sid>:<stage>`.
- Each child tagged with `stage` and `session_id`; non-zero metrics (`duration_ms`, `cost_usd`, `turns`, `tokens_in`, `tokens_out`).
- `merge` stage MLflow emission is **unverified** in current code — if absent after the wiring change, file a follow-up; not a blocker for smoke success.

## Success Criteria

- Issue reaches `stage:merge` without hitting `stage:blocked`.
- PR contains a runnable `patient-intake` CLI plus passing pytest. Code quality can be rough; correctness and test pass are the bar.
- MLflow shows the nested session/stage structure described above with the expected metric keys.
- Human merge completes cleanly. Post-merge state is quiescent.

## Known Failure Modes

- **Bootstrap confusion:** blank repo forces the agent to choose a Python toolchain. Watch the spec stage for this; if the agent picks something odd, it's signal for the prompt layer, not a smoke-test failure.
- **MLflow auth:** `MlflowTelemetry.verify_reachable()` raises fast. Any such error in stage logs points to secret wiring, not the engine.
- **Label races:** Mode 2 depends on label ordering. Simultaneous events on the same issue could produce duplicate stage invocations. Rare; noted.
- **Self-approving review:** review stage currently approves its own PR. Accepted for smoke. Must be addressed (separate reviewer identity) before Jira phase.
- **Branch protection surprise:** if org policy injects a reviewer rule on `main`, merge-stage approval and the human merge both block silently (only visible as a red X on the PR).

## Phase 2 Preview

Out of scope for this spec. After smoke succeeds:

1. Deploy dispatcher to shen (Dokploy compose already staged in `deploy/dokploy/`).
2. Create a second private repo wired to Jira via dispatcher `workflow_dispatch`.
3. Re-run the same seed-ticket shape, triggered by a Jira issue.

Phase 2 gets its own spec and plan when we get there.
