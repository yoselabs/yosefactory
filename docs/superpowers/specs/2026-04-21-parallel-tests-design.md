# Parallel Test Execution — Design

**Date:** 2026-04-21
**Status:** Design approved, pending implementation plan
**Scope:** MVP. Parallelize the existing pytest suite; fix only what breaks.

## Goal

Make `make test` run the 530-test suite under `pytest-xdist` with a worker per CPU. Pre-empt the one globally-shared-state leak we already know about (MLflow tracking URI / active run); handle everything else on a break-and-fix basis with a `@pytest.mark.serial` escape hatch.

The immediate pain point: slow feedback on the dev loop. Today the suite can hang outright on certain integration tests (an earlier run emitted nothing matching a progress filter across 10 minutes and was killed). Even the happy-path suite is uncomfortably slow for iterative work. Parallel execution plus isolation hygiene should cut wall-clock to minutes or less on typical dev machines.

## Non-Goals

- No `pytest-timeout` enforcement. Slow tests stay slow; parallelism masks most of the pain.
- No split between unit and integration lanes. Everything runs together under xdist.
- No pre-emptive audit of the 56 existing `monkeypatch`/subprocess call sites. Audit only what actually breaks under `-n auto`.
- No `xdist-group` load-balancing tuning. Flat `-n auto` is the target.
- No CI budget or absolute wall-clock target. "Substantially faster" is the bar; we'll know it when we see it.

## Known Shared-State Vectors

Enumerated once so the isolation fixture can close the biggest hole pre-emptively.

| Vector | Severity | Mitigation |
|---|---|---|
| `mlflow.set_tracking_uri(...)` — process-global within a worker | High | Autouse fixture resets tracking URI per test |
| `mlflow.active_run()` — process-global open-run state | High | Autouse fixture ends any open run between tests |
| `monkeypatch.setenv("HOME", ...)` — per-test, auto-revert | Safe | None needed |
| `monkeypatch.chdir(...)` — per-test, auto-revert | Safe | None needed |
| Raw `os.chdir(...)` without monkeypatch | Medium if present | Audit on break; fix to `monkeypatch.chdir` |
| Hardcoded `/tmp/foo` paths (not `tmp_path`) | Medium if present | Audit on break; fix to `tmp_path` |
| External network (real MLflow/GH/Anthropic) | High | Not in MVP scope; flaky tests hitting real services get `@pytest.mark.serial` as a temporary flag and a follow-up ticket |
| Filesystem locks, fixed ports | Low risk in this codebase | Mark `@pytest.mark.serial` if encountered |

## Architecture

### 1. Dependency

Add `pytest-xdist>=3.6` to `pyproject.toml`'s `[dev]` group next to `pytest-asyncio`. `uv sync --group dev` picks it up.

### 2. Invocation

Update `Makefile`'s `test` target to pass `-n auto`. Existing coverage flags stay — xdist composes with `pytest-cov` via its `--cov-branch` and combined-data-file mode.

### 3. Autouse MLflow-reset fixture (`tests/conftest.py`)

```python
@pytest.fixture(autouse=True)
def _reset_mlflow_global_state(tmp_path: Path) -> Iterator[None]:
    """Isolate MLflow's process-global state between tests.

    MLflow keeps tracking URI and the active-run stack on module-level
    globals. Under xdist each worker is its own process, but within a
    worker tests run serially and can still pollute each other.
    Reset both before and after each test.
    """
    import mlflow

    # Before: point to an isolated per-test file store and close any stray run.
    mlflow.set_tracking_uri(f"file://{tmp_path / 'mlflow'}")
    while mlflow.active_run() is not None:
        mlflow.end_run(status="KILLED")

    yield

    # After: same cleanup so the next test starts clean.
    while mlflow.active_run() is not None:
        mlflow.end_run(status="KILLED")
```

**Scope of this fixture:** applies to every test. Tests that need a specific tracking URI (e.g. `test_local_fallback_prefers_env_when_set`) use `monkeypatch.setenv("MLFLOW_TRACKING_URI", ...)` — the factory reads env fresh, so the autouse default doesn't interfere. Tests that manipulate MLflow directly get a clean slate automatically.

**Why autouse vs opt-in:** ~10 test files touch MLflow today. Opt-in means every one of them has to request the fixture; drift is guaranteed. Autouse is the safer default when the vector is global state.

### 4. Serial escape hatch

Register a `serial` marker in `pyproject.toml`'s `[tool.pytest.ini_options].markers`. `make test` runs:

```bash
uv run pytest -n auto -m "not serial"
uv run pytest -m "serial"
```

Second invocation is serial and only runs tests explicitly opted in. Zero tests marked on day one.

### 5. Break-and-fix pass

Single round: run `pytest -n auto`, triage failures into three buckets:

- **Hardcoded path / missing `tmp_path`** → fix to use `tmp_path`.
- **Raw `os.chdir`** → replace with `monkeypatch.chdir`.
- **Inherent shared global state** (filesystem lock, fixed port, real-network call sharing a mock layer) → `@pytest.mark.serial` with a one-line comment explaining why; open a follow-up ticket to deflake.

This triage happens inside the implementation session; it's not a plan of its own.

## Testing the Testing Infrastructure

Three sanity checks, not formal tests:

1. `make test` exits green on a clean checkout.
2. Re-run three times in a row; zero flakes across all three runs (catches ordering-sensitive leaks the first run happened to survive).
3. `pytest -m serial` runs only marked tests; count = 0 on day one (or the count matches the triage decisions above, with each annotated).

## Success Criteria

- `make test` green under `-n auto` with zero flakes across three consecutive runs.
- Wall-clock substantially below the pre-change baseline. No absolute number committed; "substantially" = the user doesn't feel the need to kill `make test` from the shell.
- `@pytest.mark.serial` exists as a registered marker; any tests using it have a one-line justification comment.
- `tests/conftest.py` gained one autouse fixture. No other test files modified unless flagged by the break-and-fix pass.

## Follow-ups (out of scope; file when encountered)

- Tests that hit real external services (MLflow/GH/Anthropic) should be mocked or moved behind a `@pytest.mark.integration` opt-in. Tagged `serial` today as a workaround.
- If xdist overhead outweighs gains for the unit-only subset, consider a `--no-xdist` dev loop toggle. Measure before acting.
- `pytest-timeout` may become necessary if a real hang sneaks past xdist worker timeouts. Defer.
