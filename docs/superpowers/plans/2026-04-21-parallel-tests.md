# Parallel Test Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the 530-test suite under `pytest-xdist` with one worker per CPU; fix whatever breaks to keep it green.

**Architecture:** Add `pytest-xdist` to dev deps. Register a `serial` pytest marker. Autouse fixture in `tests/conftest.py` resets MLflow process-global state (tracking URI + active run) per test. `make test` runs `-n auto -m "not serial"` then a serial pass for marked-only. Fix breakages encountered during the break-and-fix pass; mark unfixable ones `@pytest.mark.serial` with a one-line justification.

**Tech Stack:** pytest, pytest-xdist, pytest-asyncio, pytest-cov, uv, GNU make.

**Spec:** `docs/superpowers/specs/2026-04-21-parallel-tests-design.md`

---

## File Structure

**Modify:**
- `pyproject.toml` — add `pytest-xdist>=3.6` to `[dev]`; register `serial` marker under `[tool.pytest.ini_options].markers`.
- `Makefile` — `test` target becomes a two-pass invocation (parallel + serial).
- `tests/conftest.py` — add autouse MLflow-reset fixture.
- Individual test files touched by the break-and-fix pass (unknown until we run).

**Do not add:** new test files, new production modules, new fixtures beyond the one autouse.

---

## Task 1: Add `pytest-xdist` dep + register `serial` marker

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1.1: Add `pytest-xdist` to the `[dev]` group**

Open `pyproject.toml` and find the `dev = [...]` array under `[dependency-groups]` (or `[tool.uv.dev-dependencies]`, depending on layout). Insert `"pytest-xdist>=3.6",` alongside the other `pytest-*` entries. Keep alphabetical order if the group already uses one.

- [ ] **Step 1.2: Register the `serial` marker**

Find `[tool.pytest.ini_options]` in `pyproject.toml`. The existing block has:

```toml
markers = ["unit", "integration"]
```

Change to:

```toml
markers = [
    "unit",
    "integration",
    "serial: test cannot run under pytest-xdist (shared global state); run in serial pass only",
]
```

- [ ] **Step 1.3: Sync deps**

Run: `uv sync --group dev`
Expected: `pytest-xdist` installs cleanly; no other dep changes.

- [ ] **Step 1.4: Verify `pytest-xdist` is importable**

Run: `uv run python -c "import xdist; print(xdist.__version__)"`
Expected: prints `3.6.x` or newer.

- [ ] **Step 1.5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add pytest-xdist; register 'serial' pytest marker"
```

---

## Task 2: Autouse MLflow-reset fixture in `tests/conftest.py`

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 2.1: Read the current conftest**

Open `tests/conftest.py`. Today it exports one fixture (`dispatch_context_factory`). The new fixture is additive — do not modify or remove anything.

- [ ] **Step 2.2: Add imports at the top of the file (after existing imports)**

```python
from collections.abc import Iterator
from pathlib import Path
```

(If either is already imported, skip the duplicate.)

- [ ] **Step 2.3: Append the autouse fixture**

Append at the end of `tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _reset_mlflow_global_state(tmp_path: Path) -> Iterator[None]:
    """Isolate MLflow's process-global state between tests.

    MLflow stores the tracking URI and active-run stack on module-level
    globals. Under pytest-xdist each worker is its own process, but within
    a worker tests run serially and can still pollute each other. Reset
    before and after every test.

    Tests that need a specific MLflow URI should set
    ``MLFLOW_TRACKING_URI`` via ``monkeypatch.setenv`` — the factories in
    ``a2sdlc.evaluation.telemetry`` read env on each call, so this
    autouse default does not interfere.
    """
    import mlflow  # noqa: PLC0415

    mlflow.set_tracking_uri(f"file://{tmp_path / 'mlflow-autouse'}")
    while mlflow.active_run() is not None:
        mlflow.end_run(status="KILLED")

    yield

    while mlflow.active_run() is not None:
        mlflow.end_run(status="KILLED")
```

- [ ] **Step 2.4: Run the existing telemetry tests to confirm the autouse fixture doesn't break them**

Run: `uv run pytest tests/evaluation/test_telemetry.py -v`
Expected: 11 passed (same count as today), wall-clock under 5s.

If anything fails with `RESOURCE_DOES_NOT_EXIST` or `Run with UUID ... is in state KILLED but expected RUNNING`, the fixture is closing a run that the test is still in. Investigate the specific failing test — the most likely cause is a test fixture that opens `mlflow.start_run(...)` before the autouse teardown gets a chance to kill it. Usually harmless: the test itself re-opens a fresh run.

- [ ] **Step 2.5: Commit**

```bash
git add tests/conftest.py
git commit -m "test: autouse fixture resetting MLflow global state per test"
```

---

## Task 3: Update `Makefile` `test` target to run parallel + serial passes

**Files:**
- Modify: `Makefile`

- [ ] **Step 3.1: Inspect the current `test` target**

Run: `grep -A 4 "^test:" Makefile`
Expected: a target invoking `uv run pytest` with coverage flags. Note the exact flags — they'll be preserved.

- [ ] **Step 3.2: Replace the `test` target body**

Example transformation. If today the target is:

```makefile
test:
	uv run pytest --cov=a2sdlc --cov-report=term-missing --cov-branch
```

Change to:

```makefile
test:
	uv run pytest -n auto -m "not serial" --cov=a2sdlc --cov-report=term-missing --cov-branch
	uv run pytest -m "serial" --cov=a2sdlc --cov-report=term-missing --cov-branch --cov-append
```

Two passes:
1. Parallel workers, excluding `serial`-marked tests.
2. Serial-only pass for the escape hatch. `--cov-append` merges coverage into the same `.coverage` data file.

If the original target used different flags, preserve them verbatim — just split into the two-pass structure above.

- [ ] **Step 3.3: Verify Make parses the target**

Run: `make -n test`
Expected: prints the two `uv run pytest` commands without running them. If Make errors on syntax, fix the target before continuing.

- [ ] **Step 3.4: Commit**

```bash
git add Makefile
git commit -m "build(make): run tests in parallel then serial pass"
```

---

## Task 4: Break-and-fix pass

**Files:**
- Individual test files (unknown until we run)

This task is exploratory — there's no a-priori list of breakages. The goal is to run the parallel suite, triage each failure, fix or mark, repeat until green.

- [ ] **Step 4.1: Run the parallel pass**

Run: `make test 2>&1 | tee /tmp/a2sdlc-parallel-first-run.log`

Three outcomes:
- **All pass:** skip to Task 5.
- **Some fail:** continue to 4.2.
- **Suite hangs (no output for >5 min):** kill with `Ctrl-C`; narrow down by running subsets (`uv run pytest -n auto tests/evaluation/`, then `tests/adapters/`, etc.) until the hanging file is identified. The hanging file almost certainly hits real network or a subprocess that doesn't terminate under xdist. Mark the specific test with `@pytest.mark.serial` and a comment like `# Hangs under xdist; hits real network. Deflake: mock the HTTP call or use a fake adapter.` Commit and re-run.

- [ ] **Step 4.2: Triage each failure**

For each failing test name in the log:

Run it in isolation (without xdist) to confirm it's a parallelism issue, not a latent bug:

```bash
uv run pytest path/to/test_file.py::test_name -v
```

If it **passes in isolation**, the failure is xdist-induced. Categorize and fix:

| Symptom | Fix |
|---|---|
| Hardcoded path like `/tmp/something-fixed` collides with another worker | Replace with `tmp_path` fixture |
| Raw `os.chdir(...)` without `monkeypatch.chdir` | Replace with `monkeypatch.chdir(target)` |
| Test shares a real external service (MLflow remote, GH API, Anthropic) with another test | Add `@pytest.mark.serial` with a one-line `# <reason>` comment; file a follow-up |
| Test depends on a specific working-directory that another test changed out from under it | Either `monkeypatch.chdir` for the test or mark `@pytest.mark.serial` |
| Test uses a fixed port or filesystem lock | Mark `@pytest.mark.serial` |

If it **fails in isolation too**, that's a latent bug unrelated to parallelism. Fix it as a normal test failure (or mark `@pytest.mark.skip` with a bug reference if out of scope — but prefer fixing).

- [ ] **Step 4.3: Commit fixes in small batches**

Each logical group of fixes is its own commit:

```bash
git add tests/path/test_whatever.py
git commit -m "test: use tmp_path instead of hardcoded /tmp path (for xdist)"
```

```bash
git add tests/path/test_other.py
git commit -m "test(serial): mark test_slow_mlflow_integration serial; hits real network"
```

Prefer specific over general commit messages — the log is a permanent record of what leaked.

- [ ] **Step 4.4: Re-run until green**

Run: `make test`
Expected: both passes complete, exit 0. If still red, loop back to 4.2.

**If the loop exceeds 5 iterations**, stop and escalate — either the suite has systemic shared-state issues the MVP can't absorb, or a specific test needs deeper refactoring. Report the remaining failures and ask for scope expansion.

---

## Task 5: Stability verification (3-run gauntlet)

**Files:** none.

- [ ] **Step 5.1: Run `make test` three times, capturing each exit code**

```bash
for i in 1 2 3; do
  echo "--- Run $i ---"
  make test && echo "Run $i: PASS" || echo "Run $i: FAIL"
done
```

Expected: all three say `PASS`.

If any run fails, identify the flake (note the test name in the output), triage per Task 4 rules, commit the fix, and restart the 3-run count from zero.

- [ ] **Step 5.2: Record wall-clock baselines**

Run: `time make test 2>&1 | tail -3`
Expected: the `real` wall-clock time. Record it — useful for the follow-up note.

- [ ] **Step 5.3: Count `serial`-marked tests**

Run: `uv run pytest --collect-only -m serial -q 2>&1 | grep -E "^[0-9]+ tests?" | tail -1`

If the count is non-zero, read each marked test's justification comment. Each must explain *why* the test can't run under xdist. If any lacks a comment, add one now.

- [ ] **Step 5.4: Add a follow-up note if the serial count is non-zero**

If any tests are marked `serial`, append to `TODO.md` under the existing `## Telemetry follow-ups` section (or create `## Test infrastructure follow-ups` if the former doesn't exist):

```markdown
## Test infrastructure follow-ups

- [ ] Deflake <N> tests marked `@pytest.mark.serial` — see inline comments in: <list of file paths>. Each one is a separate deflake (usually: mock the real service, replace the subprocess, or refactor the shared fixture).
```

- [ ] **Step 5.5: Commit the TODO update (if any) and verify**

```bash
git add TODO.md
git commit -m "docs: parallel-test follow-ups (deflake serial-marked tests)"
```

Final sanity:

```bash
make test
```

Expected: green. Done.

---

## Self-Review Notes

- **Spec coverage:** all five sections of the spec (dep, invocation, autouse fixture, serial marker, break-and-fix) map to Tasks 1–4. Stability check (Task 5) covers the "three consecutive runs" success criterion from the spec. No gaps.
- **Placeholders:** Task 4 is intentionally exploratory — it's a triage loop, not a sequence of pre-written fixes. The triage table is the "instruction set" for that loop. This is not a placeholder, it's a runbook. The "5 iteration" escape hatch at 4.4 prevents infinite looping.
- **Type/name consistency:** `pytest-xdist>=3.6` referenced identically across Tasks 1 and 3. `@pytest.mark.serial` marker name consistent across Tasks 1, 3, 4, 5. Fixture name `_reset_mlflow_global_state` only used in Task 2. `MLFLOW_TRACKING_URI` spelling matches telemetry module usage.
- **Scope:** single subsystem (test infrastructure). One plan.
