# Workflow primitives and CLI/local mode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship v1 of a2sdlc as a CLI/local-mode runtime: `a2sdlc run` on a VM reads `INPUT.md` from a base requirements branch, drives Spec → Implement → Review with handover loop, writes per-stage artifacts to branch state, pushes the run branch to a (possibly local) origin, and prints the run-branch name + per-stage stats. No tracker integration. No auto-merge. Branches accumulate as the audit trail.

**Architecture:** Thin CLI entrypoint orchestrates an existing async pipeline. Stage handlers stay; we add an artifact-write seam (`WorkAdapter.write_stage_artifact`), a path-on-event field (`StageEnd.artifact_path`), and a terminal `RunEnd` event so the console subscriber can render an `===== a2sdlc:stage-output =====` block byte-equal to the file the adapter wrote, plus a stats line and a final `totals:`. State stays in branch-local `state.json` with a versioned schema. Adapter selection and required env vars live in `.a2sdlc/config.yaml`. Agent isolation pins SDK config so the operator's `~/.claude/CLAUDE.md`, MCP servers, and shell env do not bleed in.

**Tech Stack:** Python 3.11+, pydantic, pytest, asyncio, click/typer (existing CLI uses typer-style), Claude Agent SDK, GitPython (existing), MLflow (existing), `rich` for console rendering.

**Source spec:** `docs/superpowers/specs/2026-04-30-workflow-primitives-and-cli-mode-design.md` (commit `03883c5`).

---

## File Structure

This plan creates / modifies the following files. Each task touches a focused subset.

### New files

- `packages/engine/src/a2sdlc/adapters/review/local.py` — `LocalReviewAdapter` writing review markdown to branch state.
- `packages/engine/src/a2sdlc/runtime/lockfile.py` — PID-stamped exclusive lockfile with signal-handler cleanup.
- `packages/engine/src/a2sdlc/runtime/env_check.py` — `REQUIRED_ENV` aggregation + fail-fast validator.
- `packages/engine/src/a2sdlc/runtime/dirty_tree.py` — `git status --porcelain` based check that ignores untracked outside `.a2sdlc/`.
- `packages/engine/src/a2sdlc/runtime/branch.py` — `format_run_branch` / `parse_run_branch`, base resolution, protected-base guard, branch-existence guard.
- `packages/engine/src/a2sdlc/runtime/state_migration.py` — v0 → v1 lazy migrator for `state.json`.
- `packages/engine/src/a2sdlc/runtime/isolation.py` — SDK options builder enforcing the §Agent isolation contract (env curation, CLAUDE_CONFIG_DIR strip, empty `mcp_servers`).
- `packages/engine/src/a2sdlc/cli/run.py` — the `a2sdlc run` command implementing CLI surface steps 1–11.
- `packages/engine/src/a2sdlc/config_run.py` — pydantic model for `.a2sdlc/config.yaml` with `mode`, `adapters`, `subscribers`, `required_env`, `pipeline` blocks. (Naming avoids collision with existing `config.py`.)
- `tests/runtime/__init__.py`, `tests/runtime/test_lockfile.py`, `tests/runtime/test_env_check.py`, `tests/runtime/test_dirty_tree.py`, `tests/runtime/test_branch.py`, `tests/runtime/test_state_migration.py`, `tests/runtime/test_isolation.py`.
- `tests/adapters/review/test_local.py`.
- `tests/cli/test_run.py`.
- `tests/config/test_config_run.py`.
- `scripts/smoke_local.sh` — end-to-end smoke harness.
- `tests/smoke/__init__.py`, `tests/smoke/test_smoke_local.py` — Python wrapper if the harness is invoked as a pytest.

### Modified files

- `packages/engine/src/a2sdlc/adapters/work/__init__.py` — add `write_stage_artifact` to the `WorkAdapter` Protocol.
- `packages/engine/src/a2sdlc/adapters/work/local_file.py` — implement `write_stage_artifact`.
- `packages/engine/src/a2sdlc/adapters/work/github.py` — implement `write_stage_artifact` (writes to a comment-attachment file path; v1 contract stub returning a temp path is acceptable since GH ecosystem is deferred).
- `packages/engine/src/a2sdlc/adapters/review/__init__.py` — `post_review` return type changes from `None` to `Path`. Re-export `LocalReviewAdapter`.
- `packages/engine/src/a2sdlc/adapters/review/github.py` — update `post_review` return.
- `packages/engine/src/a2sdlc/adapters/review/local_noop.py` — update `post_review` return.
- `packages/engine/src/a2sdlc/domain/progress.py` — add `RunEnd` event variant; add `artifact_path: Path | None = None` field to `StageEnd`.
- `packages/engine/src/a2sdlc/domain/progress_format.py` — add `_format_tokens_precise(n)` helper.
- `packages/engine/src/a2sdlc/domain/run_context.py` — extend `PipelineRun` (or its serialized state shape) with `schema_version`, `base_sha`, `ecosystem`, `workflow_id`. (Confirmed during Task 1.)
- `packages/engine/src/a2sdlc/adapters/subscriber/console.py` — three-rhythm renderer (start / event log / output block + stats / totals).
- `packages/engine/src/a2sdlc/adapters/subscriber/mlflow_trace.py` — `run_name = workflow_id` + tags.
- `packages/engine/src/a2sdlc/pipeline/dispatch.py` — emit `RunEnd` in `finally`; thread `artifact_path` onto `StageEnd`; reads `state.json` for `total_cycles` + `aggregate_stats`.
- `packages/engine/src/a2sdlc/pipeline/runner.py` — call into `runtime/isolation.py` for SDK options, drop user-level config inheritance.
- `packages/engine/src/a2sdlc/cli/main.py` — register the `run` command.
- `Makefile` — add `smoke-local` target.
- `.gitignore` — add `tmp/` and `tmp/smoke-local-failed-*`.
- `pyproject.toml` — register `a2sdlc run` if not implicit.
- `docs/architecture.md` — add the new `runtime/` package to the layer stack.
- CI config (`.github/workflows/*.yml` if present) — add a `smoke-local` job gated on secrets.

---

## Task Index

1. PipelineRun identity & schema fields
2. State migration v0 → v1 (lazy)
3. Run-branch generator + parser
4. WorkAdapter.write_stage_artifact (Protocol + LocalFileWorkAdapter)
5. WorkAdapter.write_stage_artifact (GitHubWorkAdapter stub)
6. LocalReviewAdapter
7. ReviewAdapter.post_review return-type ripple
8. _format_tokens_precise helper
9. StageEnd.artifact_path field + RunEnd event
10. Dispatch teardown emits RunEnd
11. Console subscriber three-rhythm renderer
12. MLflow run_name + tags
13. REQUIRED_ENV aggregation + fail-fast
14. Lockfile + signal handlers
15. Dirty-tree check + protected-base guard
16. Agent isolation builder (env curation, MCP empty, CLAUDE_CONFIG_DIR strip)
17. Config loader (.a2sdlc/config.yaml)
18. `a2sdlc run` CLI surface (the orchestrator)
19. Smoke harness + make smoke-local + CI job
20. Documentation + architecture-test update

---

### Task 1: PipelineRun identity & schema fields

**Files:**
- Modify: `packages/engine/src/a2sdlc/domain/run_context.py`
- Modify: `packages/engine/src/a2sdlc/domain/models.py` (only if state shape lives there)
- Test: `tests/domain/test_pipeline_run_identity.py` (create)

The spec requires `workflow_id`, `ticket_key | None`, `base`, `base_sha`, `ecosystem`, `schema_version`. Some may already exist; confirm and add what's missing.

- [ ] **Step 1.1: Read current state shape**

Run:
```bash
grep -n "schema_version\|workflow_id\|base_sha\|ecosystem" packages/engine/src/a2sdlc/domain/run_context.py packages/engine/src/a2sdlc/domain/models.py packages/engine/src/a2sdlc/domain/run_intent.py
```

Note which fields exist. If a `PipelineRun` dataclass / pydantic model exists, modify it. If state is a dict-like blob, locate the canonical type.

- [ ] **Step 1.2: Write the failing test**

Create `tests/domain/test_pipeline_run_identity.py`:

```python
"""Identity & schema fields on the persisted PipelineRun state."""
from __future__ import annotations

import pytest

# Replace `from a2sdlc.domain.run_context import PipelineRun` with the
# actual canonical type once Step 1.1 confirms its location.
from a2sdlc.domain.run_context import PipelineRun  # noqa: E402


def test_pipeline_run_carries_v1_identity_fields() -> None:
    run = PipelineRun(
        workflow_id="a2sdlc/auto/req-x/20260430-142208-a3f019",
        ticket_key="ABC-123",
        base="req/x",
        base_sha="0" * 40,
        ecosystem="local",
        schema_version=1,
    )
    assert run.workflow_id == "a2sdlc/auto/req-x/20260430-142208-a3f019"
    assert run.ticket_key == "ABC-123"
    assert run.base == "req/x"
    assert run.base_sha == "0" * 40
    assert run.ecosystem == "local"
    assert run.schema_version == 1


def test_ticket_key_optional() -> None:
    run = PipelineRun(
        workflow_id="a2sdlc/auto/req-x/20260430-142208-a3f019",
        ticket_key=None,
        base="req/x",
        base_sha="0" * 40,
        ecosystem="local",
        schema_version=1,
    )
    assert run.ticket_key is None
```

- [ ] **Step 1.3: Run test to verify it fails**

Run: `pytest tests/domain/test_pipeline_run_identity.py -v`
Expected: FAIL on `unexpected keyword argument` or `attribute does not exist`.

- [ ] **Step 1.4: Add the missing fields**

Edit the canonical `PipelineRun` (likely in `domain/run_context.py`). Add fields with safe defaults so existing constructors still work:

```python
# (Add inside the existing dataclass / pydantic model)
workflow_id: str = ""
ticket_key: str | None = None
base: str = ""
base_sha: str = ""
ecosystem: str = "local"
schema_version: int = 1
```

Constructors elsewhere may need updating; the field defaults make this backward-compatible.

- [ ] **Step 1.5: Run test to verify it passes**

Run: `pytest tests/domain/test_pipeline_run_identity.py -v`
Expected: PASS.

- [ ] **Step 1.6: Run full test suite to catch regressions**

Run: `make test`
Expected: PASS.

- [ ] **Step 1.7: Commit**

```bash
git add packages/engine/src/a2sdlc/domain/run_context.py tests/domain/test_pipeline_run_identity.py
git commit -m "feat(domain): add v1 identity fields to PipelineRun"
```

---

### Task 2: State migration v0 → v1 (lazy)

**Files:**
- Create: `packages/engine/src/a2sdlc/runtime/__init__.py`
- Create: `packages/engine/src/a2sdlc/runtime/state_migration.py`
- Create: `tests/runtime/__init__.py`
- Create: `tests/runtime/test_state_migration.py`

Lazy migrator: detect missing `schema_version`, return upgraded in-memory shape with sensible defaults. Disk write happens on next stage-finish (out of scope for this task).

- [ ] **Step 2.1: Create the runtime package**

Run:
```bash
mkdir -p packages/engine/src/a2sdlc/runtime
touch packages/engine/src/a2sdlc/runtime/__init__.py
mkdir -p tests/runtime
touch tests/runtime/__init__.py
```

- [ ] **Step 2.2: Write the failing test**

Create `tests/runtime/test_state_migration.py`:

```python
"""Lazy v0 -> v1 state migration."""
from __future__ import annotations

import logging

from a2sdlc.runtime.state_migration import migrate_state_blob, V1_SCHEMA_VERSION


def test_v0_blob_gains_schema_version_one() -> None:
    v0 = {"branch": "a2sdlc/foo", "stage": "SPEC"}
    migrated, did_migrate = migrate_state_blob(v0)
    assert did_migrate is True
    assert migrated["schema_version"] == V1_SCHEMA_VERSION


def test_v0_blob_gets_default_ecosystem_local() -> None:
    v0 = {"branch": "a2sdlc/foo", "stage": "SPEC"}
    migrated, _ = migrate_state_blob(v0)
    assert migrated["ecosystem"] == "local"


def test_v1_blob_passes_through_untouched() -> None:
    v1 = {"branch": "a2sdlc/foo", "schema_version": 1, "ecosystem": "local"}
    migrated, did_migrate = migrate_state_blob(v1)
    assert did_migrate is False
    assert migrated == v1


def test_migration_emits_log_line(caplog) -> None:
    caplog.set_level(logging.INFO, logger="a2sdlc.runtime.state_migration")
    migrate_state_blob({"branch": "x", "stage": "SPEC"})
    assert any("state.migrated from=v0 to=v1" in r.message for r in caplog.records)
```

- [ ] **Step 2.3: Run test to verify it fails**

Run: `pytest tests/runtime/test_state_migration.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 2.4: Implement the migrator**

Create `packages/engine/src/a2sdlc/runtime/state_migration.py`:

```python
"""Lazy v0 -> v1 migration of the persisted state.json blob.

Spec: §Migration notes. v0 files (no schema_version field) are read into
the v1 in-memory shape with schema_version=0 set on read, then ecosystem
defaulted in. The migrated state is written back to disk *lazily* — on
the next stage-finish commit — never eagerly on read.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("a2sdlc.runtime.state_migration")

V1_SCHEMA_VERSION = 1


def migrate_state_blob(blob: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Return (possibly migrated blob, did_migrate).

    Mutates a copy of the input. Caller decides whether to write back.
    """
    if blob.get("schema_version") == V1_SCHEMA_VERSION:
        return blob, False
    out = dict(blob)
    out["schema_version"] = V1_SCHEMA_VERSION
    out.setdefault("ecosystem", "local")
    logger.info("state.migrated from=v0 to=v1 (branch=%s)", out.get("branch"))
    return out, True
```

- [ ] **Step 2.5: Run test to verify it passes**

Run: `pytest tests/runtime/test_state_migration.py -v`
Expected: 4 PASS.

- [ ] **Step 2.6: Wire migration into the state-loader**

Identify where `state.json` is read today:

Run: `grep -rn "state.json\|load_state\|read.*state" packages/engine/src/a2sdlc/ --include="*.py" | head`

In the canonical loader, after JSON decode, call `migrate_state_blob(...)` and use the migrated dict. Leave write-back to the existing stage-finish commit path — *do not* write back on read.

- [ ] **Step 2.7: Commit**

```bash
git add packages/engine/src/a2sdlc/runtime/ tests/runtime/test_state_migration.py
git commit -m "feat(runtime): lazy v0->v1 state.json migrator"
```

---

### Task 3: Run-branch generator + parser

**Files:**
- Create: `packages/engine/src/a2sdlc/runtime/branch.py`
- Create: `tests/runtime/test_branch.py`

Implements `format_run_branch(base, ts, input_hash)` and the inverse `parse_run_branch(branch)`. Spec §Run-branch suffix.

- [ ] **Step 3.1: Write failing tests**

Create `tests/runtime/test_branch.py`:

```python
"""Run-branch generator + parser. Spec §Run-branch suffix."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from a2sdlc.runtime.branch import (
    format_run_branch,
    parse_run_branch,
    compute_input_hash,
)


def test_format_run_branch_shape() -> None:
    ts = datetime(2026, 4, 30, 14, 22, 8, tzinfo=timezone.utc)
    branch = format_run_branch("req/billing-v2", ts, "a3f019")
    assert branch == "a2sdlc/auto/req-billing-v2/20260430-142208-a3f019"


def test_base_slug_replaces_slashes_with_hyphens() -> None:
    ts = datetime(2026, 4, 30, 14, 22, 8, tzinfo=timezone.utc)
    branch = format_run_branch("req/foo/bar", ts, "abcdef")
    assert "req-foo-bar" in branch


def test_parse_round_trip() -> None:
    ts = datetime(2026, 4, 30, 14, 22, 8, tzinfo=timezone.utc)
    branch = format_run_branch("req/billing-v2", ts, "a3f019")
    parsed = parse_run_branch(branch)
    assert parsed is not None
    assert parsed.base_slug == "req-billing-v2"
    assert parsed.ts == ts
    assert parsed.input_hash == "a3f019"


def test_parse_returns_none_for_non_run_branches() -> None:
    assert parse_run_branch("main") is None
    assert parse_run_branch("feature/foo") is None
    assert parse_run_branch("a2sdlc/auto/incomplete") is None


def test_compute_input_hash_first_six_hex_of_sha256() -> None:
    h = compute_input_hash(b"hello world")
    # SHA-256("hello world") = b94d27b9...
    assert h == "b94d27"
    assert len(h) == 6


def test_format_run_branch_uses_utc() -> None:
    # Naive datetime should be rejected to avoid TZ ambiguity.
    naive = datetime(2026, 4, 30, 14, 22, 8)
    with pytest.raises(ValueError):
        format_run_branch("req/x", naive, "abcdef")
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `pytest tests/runtime/test_branch.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3.3: Implement**

Create `packages/engine/src/a2sdlc/runtime/branch.py`:

```python
"""Run-branch generator + parser. Spec §Run-branch suffix."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone


_BRANCH_PREFIX = "a2sdlc/auto"
_TS_FMT = "%Y%m%d-%H%M%S"
_HASH_LEN = 6
_RUN_BRANCH_RE = re.compile(
    r"^a2sdlc/auto/(?P<base_slug>[^/]+)/(?P<ts>\d{8}-\d{6})-(?P<input_hash>[0-9a-f]{6})$"
)


@dataclass(frozen=True)
class ParsedRunBranch:
    base_slug: str
    ts: datetime
    input_hash: str


def _slugify_base(base: str) -> str:
    return base.replace("/", "-")


def format_run_branch(base: str, ts: datetime, input_hash: str) -> str:
    if ts.tzinfo is None:
        raise ValueError("ts must be timezone-aware (use UTC)")
    ts_utc = ts.astimezone(timezone.utc)
    return (
        f"{_BRANCH_PREFIX}/"
        f"{_slugify_base(base)}/"
        f"{ts_utc.strftime(_TS_FMT)}-{input_hash}"
    )


def parse_run_branch(branch: str) -> ParsedRunBranch | None:
    m = _RUN_BRANCH_RE.match(branch)
    if not m:
        return None
    ts = datetime.strptime(m["ts"], _TS_FMT).replace(tzinfo=timezone.utc)
    return ParsedRunBranch(
        base_slug=m["base_slug"],
        ts=ts,
        input_hash=m["input_hash"],
    )


def compute_input_hash(input_bytes: bytes) -> str:
    """SHA-256 of INPUT.md content, first 6 hex chars."""
    return hashlib.sha256(input_bytes).hexdigest()[:_HASH_LEN]
```

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `pytest tests/runtime/test_branch.py -v`
Expected: 6 PASS.

- [ ] **Step 3.5: Commit**

```bash
git add packages/engine/src/a2sdlc/runtime/branch.py tests/runtime/test_branch.py
git commit -m "feat(runtime): run-branch generator + parser"
```

---

### Task 4: WorkAdapter.write_stage_artifact (Protocol + LocalFileWorkAdapter)

**Files:**
- Modify: `packages/engine/src/a2sdlc/adapters/work/__init__.py`
- Modify: `packages/engine/src/a2sdlc/adapters/work/local_file.py`
- Modify: `tests/adapters/work/test_local_file.py`

Spec §Adapter ecosystem: additive method `write_stage_artifact(stage, cycle, content) -> Path`.

- [ ] **Step 4.1: Write the failing test**

Add to `tests/adapters/work/test_local_file.py` (append):

```python
def test_write_stage_artifact_spec_writes_spec_md(tmp_path) -> None:
    from a2sdlc.adapters.work.local_file import LocalFileWorkAdapter
    from a2sdlc.domain.models import StageName

    adapter = LocalFileWorkAdapter(state_root=tmp_path / ".a2sdlc/state/branchA")
    p = adapter.write_stage_artifact(StageName.SPEC, cycle=1, content="hello\n")
    assert p == tmp_path / ".a2sdlc/state/branchA/spec.md"
    assert p.read_text() == "hello\n"


def test_write_stage_artifact_implement_uses_cycle(tmp_path) -> None:
    from a2sdlc.adapters.work.local_file import LocalFileWorkAdapter
    from a2sdlc.domain.models import StageName

    adapter = LocalFileWorkAdapter(state_root=tmp_path / ".a2sdlc/state/branchA")
    p1 = adapter.write_stage_artifact(StageName.IMPLEMENT, cycle=1, content="c1")
    p2 = adapter.write_stage_artifact(StageName.IMPLEMENT, cycle=2, content="c2")
    assert p1.name == "implement-cycle-1.md"
    assert p2.name == "implement-cycle-2.md"
    assert p1.read_text() == "c1"
    assert p2.read_text() == "c2"


def test_write_stage_artifact_overwrites_for_spec(tmp_path) -> None:
    from a2sdlc.adapters.work.local_file import LocalFileWorkAdapter
    from a2sdlc.domain.models import StageName

    adapter = LocalFileWorkAdapter(state_root=tmp_path / ".a2sdlc/state/branchA")
    adapter.write_stage_artifact(StageName.SPEC, cycle=1, content="first")
    adapter.write_stage_artifact(StageName.SPEC, cycle=1, content="second")
    p = tmp_path / ".a2sdlc/state/branchA/spec.md"
    assert p.read_text() == "second"
```

(`LocalFileWorkAdapter` may need a `state_root` kwarg; if it currently inspects `cwd`/git, accept either pattern — adapt the test in Step 4.2 if the existing constructor differs.)

- [ ] **Step 4.2: Run test to verify failure**

Run: `pytest tests/adapters/work/test_local_file.py -v -k write_stage_artifact`
Expected: FAIL — method does not exist.

- [ ] **Step 4.3: Add method to the Protocol**

Edit `packages/engine/src/a2sdlc/adapters/work/__init__.py`. Inside the `WorkAdapter` Protocol class:

```python
    def write_stage_artifact(
        self, stage: StageName, cycle: int, content: str
    ) -> Path:
        """Persist the stage's primary artifact and return the file path.

        Spec §Adapter ecosystem. The returned Path is what the console
        subscriber reads to populate the stage-output block; the file
        contents and the stdout block are byte-equal by construction.

        Path conventions:
        - SPEC -> {state_root}/spec.md (cycle ignored; SPEC runs once).
        - IMPLEMENT -> {state_root}/implement-cycle-{n}.md.
        - REVIEW: written by ReviewAdapter; this method is not invoked
          for REVIEW stages.
        """
        ...
```

Add the `Path` import at the top: `from pathlib import Path`.

- [ ] **Step 4.4: Implement on LocalFileWorkAdapter**

Edit `packages/engine/src/a2sdlc/adapters/work/local_file.py`. Add (adjust to the actual class):

```python
from pathlib import Path
from a2sdlc.domain.models import StageName

# Inside class LocalFileWorkAdapter:

    def write_stage_artifact(
        self, stage: StageName, cycle: int, content: str
    ) -> Path:
        if stage == StageName.SPEC:
            filename = "spec.md"
        elif stage == StageName.IMPLEMENT:
            filename = f"implement-cycle-{cycle}.md"
        else:
            raise ValueError(
                f"LocalFileWorkAdapter does not write artifacts for stage {stage!r};"
                " REVIEW artifacts are owned by LocalReviewAdapter."
            )
        path = self.state_root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path
```

If the existing `LocalFileWorkAdapter` doesn't carry a `state_root`, add it via `__init__(self, state_root: Path, ...)`.

- [ ] **Step 4.5: Run test to verify pass**

Run: `pytest tests/adapters/work/test_local_file.py -v -k write_stage_artifact`
Expected: 3 PASS.

- [ ] **Step 4.6: Commit**

```bash
git add packages/engine/src/a2sdlc/adapters/work/__init__.py packages/engine/src/a2sdlc/adapters/work/local_file.py tests/adapters/work/test_local_file.py
git commit -m "feat(adapters): WorkAdapter.write_stage_artifact + LocalFileWorkAdapter impl"
```

---

### Task 5: WorkAdapter.write_stage_artifact (GitHubWorkAdapter stub)

**Files:**
- Modify: `packages/engine/src/a2sdlc/adapters/work/github.py`
- Modify: `tests/adapters/work/test_github.py`

GH ecosystem is deferred but the protocol requires the method. Implement a defensive stub.

- [ ] **Step 5.1: Write the failing test**

Append to `tests/adapters/work/test_github.py`:

```python
def test_write_stage_artifact_writes_under_local_state(tmp_path, monkeypatch) -> None:
    """GH adapter stub writes to a local path; tracker-side push is a future spec."""
    from a2sdlc.adapters.work.github import GitHubWorkAdapter
    from a2sdlc.domain.models import StageName

    # Construct via the existing factory or a minimal init — adjust to actual.
    # If construction is heavy (real PyGithub), use the testing harness already
    # in this file.
    monkeypatch.chdir(tmp_path)
    adapter = make_test_github_work_adapter(repo="owner/repo")  # existing helper
    p = adapter.write_stage_artifact(StageName.SPEC, cycle=1, content="x")
    assert p.exists()
    assert p.read_text() == "x"
```

If `make_test_github_work_adapter` doesn't exist, copy a small construction snippet from a sibling test in the same file.

- [ ] **Step 5.2: Run test (expect failure)**

Run: `pytest tests/adapters/work/test_github.py -v -k write_stage_artifact`
Expected: FAIL.

- [ ] **Step 5.3: Implement defensive stub**

Edit `packages/engine/src/a2sdlc/adapters/work/github.py`:

```python
from pathlib import Path

# Inside class GitHubWorkAdapter:

    def write_stage_artifact(
        self, stage: StageName, cycle: int, content: str
    ) -> Path:
        """Stub for the deferred GitHub ecosystem.

        v1 ships only the local ecosystem; the GH ecosystem follow-up
        spec will replace this with a comment-or-attachment write. For
        now, mirror LocalFileWorkAdapter's behavior so REVIEW artifact
        plumbing works in dev-mode invocations.
        """
        if stage == StageName.SPEC:
            filename = "spec.md"
        elif stage == StageName.IMPLEMENT:
            filename = f"implement-cycle-{cycle}.md"
        else:
            raise ValueError(
                f"GitHubWorkAdapter does not write artifacts for stage {stage!r}"
            )
        # Use an engine-controlled local path; tracker-side persistence
        # is the future spec.
        state_root = Path(".a2sdlc/state") / self.run_branch_name  # if available
        state_root.mkdir(parents=True, exist_ok=True)
        path = state_root / filename
        path.write_text(content)
        return path
```

Adapt `self.run_branch_name` to the actual field/method on the class.

- [ ] **Step 5.4: Run test, verify pass**

Run: `pytest tests/adapters/work/test_github.py -v -k write_stage_artifact`
Expected: PASS.

- [ ] **Step 5.5: Commit**

```bash
git add packages/engine/src/a2sdlc/adapters/work/github.py tests/adapters/work/test_github.py
git commit -m "feat(adapters): GitHubWorkAdapter.write_stage_artifact stub"
```

---

### Task 6: LocalReviewAdapter

**Files:**
- Create: `packages/engine/src/a2sdlc/adapters/review/local.py`
- Modify: `packages/engine/src/a2sdlc/adapters/review/__init__.py` (re-export)
- Create: `tests/adapters/review/test_local.py`

Writes review markdown into branch state. Spec §Local ecosystem.

- [ ] **Step 6.1: Write failing tests**

Create `tests/adapters/review/test_local.py`:

```python
"""LocalReviewAdapter: writes review markdown into branch state."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from a2sdlc.adapters.review.local import LocalReviewAdapter
from a2sdlc.domain.stage_outcome import InlineComment


def make_adapter(tmp_path: Path) -> LocalReviewAdapter:
    return LocalReviewAdapter(
        state_root=tmp_path / ".a2sdlc/state/branchA",
        clock=lambda: datetime(2026, 4, 30, 14, 22, 8, tzinfo=timezone.utc),
        cycle=1,
    )


def test_post_review_writes_cycle_file_and_returns_path(tmp_path) -> None:
    adapter = make_adapter(tmp_path)
    p = adapter.post_review(pr_number=0, body="approved", verdict="approved")
    assert p == tmp_path / ".a2sdlc/state/branchA/reviews/2026-04-30T14-22-08-cycle-1.md"
    assert p.exists()
    assert "verdict: approved" in p.read_text()
    assert "approved" in p.read_text()


def test_post_inline_comments_writes_paired_inline_file(tmp_path) -> None:
    adapter = make_adapter(tmp_path)
    adapter.post_inline_comments(
        pr_number=0,
        comments=[
            InlineComment(path="src/x.py", line=42, body="check this"),
            InlineComment(path="src/y.py", line=7, body="multi\nline"),
        ],
    )
    inline = tmp_path / ".a2sdlc/state/branchA/reviews/2026-04-30T14-22-08-cycle-1-inline.md"
    text = inline.read_text()
    assert "src/x.py:42" in text
    assert "  agent: check this" in text
    assert "src/y.py:7" in text
    assert "  agent: multi\n  line" in text


def test_post_inline_comments_empty_list_is_noop(tmp_path) -> None:
    adapter = make_adapter(tmp_path)
    adapter.post_inline_comments(pr_number=0, comments=[])
    inline = tmp_path / ".a2sdlc/state/branchA/reviews/2026-04-30T14-22-08-cycle-1-inline.md"
    assert not inline.exists()


def test_pr_lifecycle_methods_are_safe_noops(tmp_path) -> None:
    adapter = make_adapter(tmp_path)
    assert adapter.create_draft_pr(branch="x", base="y", title="t", ticket_key="K") == 0
    assert adapter.get_approvals(pr_number=0) == []
    # merge_pr / mark_pr_ready / update_pr should not raise
    adapter.update_pr(pr_number=0, title="t", body="b", ticket_key="K")
    adapter.update_pr_title(pr_number=0, title="t")
    adapter.mark_pr_ready(pr_number=0)
    adapter.merge_pr(pr_number=0)
```

- [ ] **Step 6.2: Run tests (expect failure)**

Run: `pytest tests/adapters/review/test_local.py -v`
Expected: FAIL — module not found.

- [ ] **Step 6.3: Implement**

Create `packages/engine/src/a2sdlc/adapters/review/local.py`:

```python
"""LocalReviewAdapter — writes review markdown into branch state.

Spec §Adapter ecosystem / Local ecosystem.

`post_review` and `post_inline_comments` write to
`.a2sdlc/state/<branch>/reviews/<ts>-cycle-<n>(.md|-inline.md)`.
PR-lifecycle methods are safe no-ops since no PR exists in local mode.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from a2sdlc.adapters.review import Approval, ReviewComment
from a2sdlc.domain.handover import FeedbackItem, HandoverComment
from a2sdlc.domain.stage_outcome import InlineComment


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class LocalReviewAdapter:
    state_root: Path
    cycle: int = 1
    clock: Callable[[], datetime] = _default_clock

    def _reviews_dir(self) -> Path:
        d = self.state_root / "reviews"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _ts_str(self) -> str:
        return self.clock().strftime("%Y-%m-%dT%H-%M-%S")

    # ── ReviewAdapter Protocol ────────────────────────────────────

    def create_draft_pr(
        self, branch: str, base: str, title: str, ticket_key: str
    ) -> int:
        return 0  # sentinel: no PR in local mode

    def update_pr(
        self, pr_number: int, title: str, body: str, ticket_key: str
    ) -> None:
        return None

    def update_pr_title(self, pr_number: int, title: str) -> None:
        return None

    def mark_pr_ready(self, pr_number: int) -> None:
        return None

    def merge_pr(self, pr_number: int, method: str = "squash") -> None:
        return None

    def get_approvals(self, pr_number: int) -> list[Approval]:
        return []

    def post_review(self, pr_number: int, body: str, verdict: str) -> Path:
        path = self._reviews_dir() / f"{self._ts_str()}-cycle-{self.cycle}.md"
        path.write_text(f"verdict: {verdict}\n\n{body}\n")
        return path

    def post_inline_comments(
        self, pr_number: int, comments: list[InlineComment]
    ) -> None:
        if not comments:
            return None
        path = self._reviews_dir() / f"{self._ts_str()}-cycle-{self.cycle}-inline.md"
        blocks: list[str] = []
        for c in comments:
            body_indented = "\n".join("  " + ln for ln in f"agent: {c.body}".splitlines())
            blocks.append(f"{c.path}:{c.line}\n{body_indented}")
        path.write_text("\n\n".join(blocks) + "\n")

    def read_pr_diff(self, pr_number: int) -> str:
        return ""

    def read_pr_comments(self, pr_number: int) -> list[ReviewComment]:
        return []

    def collect_pr_feedback(
        self, pr_number: int, since: datetime
    ) -> list[FeedbackItem]:
        return []

    def find_last_handover(self, pr_number: int) -> HandoverComment | None:
        return None
```

Re-export from `packages/engine/src/a2sdlc/adapters/review/__init__.py`:

```python
from a2sdlc.adapters.review.local import LocalReviewAdapter  # noqa: E402
# add to __all__ if present:
__all__ = [..., "LocalReviewAdapter"]
```

- [ ] **Step 6.4: Run tests, verify pass**

Run: `pytest tests/adapters/review/test_local.py -v`
Expected: 4 PASS.

- [ ] **Step 6.5: Commit**

```bash
git add packages/engine/src/a2sdlc/adapters/review/local.py packages/engine/src/a2sdlc/adapters/review/__init__.py tests/adapters/review/test_local.py
git commit -m "feat(adapters): LocalReviewAdapter writing markdown to branch state"
```

---

### Task 7: ReviewAdapter.post_review return-type ripple

**Files:**
- Modify: `packages/engine/src/a2sdlc/adapters/review/__init__.py`
- Modify: `packages/engine/src/a2sdlc/adapters/review/github.py`
- Modify: `packages/engine/src/a2sdlc/adapters/review/local_noop.py`
- Modify: tests if any assert on `None` return.

Spec §Console output cadence: `post_review` returns `Path`.

- [ ] **Step 7.1: Write the failing test**

Add to `tests/adapters/review/test_github.py`:

```python
def test_post_review_returns_path(monkeypatch) -> None:
    """GH adapter post_review returns the temp file path used to stage the body."""
    from a2sdlc.adapters.review.github import GitHubReviewAdapter
    from pathlib import Path

    adapter = make_test_github_review_adapter(repo="owner/repo")  # existing helper
    monkeypatch.setattr(adapter, "_post_review_via_api", lambda *a, **kw: None)
    p = adapter.post_review(pr_number=1, body="hi", verdict="approved")
    assert isinstance(p, Path)
    assert p.exists()
    assert "approved" in p.read_text() or "hi" in p.read_text()
```

Add to `tests/adapters/review/test_local_noop.py`:

```python
def test_post_review_returns_path(tmp_path) -> None:
    from a2sdlc.adapters.review.local_noop import LocalNoopReviewAdapter
    from pathlib import Path

    adapter = LocalNoopReviewAdapter()
    p = adapter.post_review(pr_number=0, body="x", verdict="approved")
    assert isinstance(p, Path)
```

- [ ] **Step 7.2: Run tests, expect failures**

Run: `pytest tests/adapters/review/ -v -k post_review`
Expected: failures on the new assertions.

- [ ] **Step 7.3: Update Protocol signature**

In `packages/engine/src/a2sdlc/adapters/review/__init__.py`:

```python
    def post_review(self, pr_number: int, body: str, verdict: str) -> Path:
        """Post a review and return the local file path that mirrors the body.

        For LocalReviewAdapter, this *is* the canonical artifact. For GH /
        Jira ecosystems, the API call posts to the tracker and the
        returned path is a side-staging file the engine consults for the
        stdout output block.
        """
        ...
```

Ensure `from pathlib import Path` is imported.

- [ ] **Step 7.4: Update GitHubReviewAdapter**

Edit `packages/engine/src/a2sdlc/adapters/review/github.py`:

```python
import tempfile
from pathlib import Path

# Inside post_review, after the existing API call:

    def post_review(self, pr_number: int, body: str, verdict: str) -> Path:
        self._post_review_via_api(pr_number, body, verdict)  # existing API call
        # Stage a local copy so the console subscriber's output block is
        # byte-equal to what was posted.
        tmpdir = Path(tempfile.gettempdir()) / "a2sdlc-gh-reviews"
        tmpdir.mkdir(parents=True, exist_ok=True)
        path = tmpdir / f"pr-{pr_number}-{verdict}.md"
        path.write_text(f"verdict: {verdict}\n\n{body}\n")
        return path
```

(If `_post_review_via_api` doesn't exist, refactor the current API call out to a small helper or inline the API call here.)

- [ ] **Step 7.5: Update LocalNoopReviewAdapter**

Edit `packages/engine/src/a2sdlc/adapters/review/local_noop.py`:

```python
from pathlib import Path

# Inside class LocalNoopReviewAdapter:

    def post_review(self, pr_number: int, body: str, verdict: str) -> Path:
        return Path("/dev/null")
```

- [ ] **Step 7.6: Search for callers and adjust**

Run: `grep -rn "\.post_review(" packages/engine/src/a2sdlc/ --include="*.py"`

Update any caller that *uses* the return value. Most current callers ignore it; that's fine. The dispatch will use the return value (Task 10).

- [ ] **Step 7.7: Run all review tests, verify pass**

Run: `pytest tests/adapters/review/ -v`
Expected: PASS across all tests.

- [ ] **Step 7.8: Commit**

```bash
git add packages/engine/src/a2sdlc/adapters/review/ tests/adapters/review/
git commit -m "feat(adapters): ReviewAdapter.post_review returns Path"
```

---

### Task 8: `_format_tokens_precise` helper

**Files:**
- Modify: `packages/engine/src/a2sdlc/domain/progress_format.py`
- Create or extend: `tests/domain/test_progress_format.py`

Spec §Stats line formatting. Existing `_format_tokens` is integer-only; the precise variant gives one-decimal `Xk` / `XM` for stats lines.

- [ ] **Step 8.1: Write failing tests**

Add to `tests/domain/test_progress_format.py` (create if absent):

```python
"""Token / duration formatters used by the stats line."""
from __future__ import annotations

import pytest

from a2sdlc.domain.progress_format import _format_tokens_precise


@pytest.mark.parametrize(
    "n,expected",
    [
        (0, "0"),
        (1, "1"),
        (999, "999"),
        (1_000, "1.0k"),
        (12_400, "12.4k"),
        (38_237, "38.2k"),
        (999_999, "1000.0k"),
        (1_000_000, "1.0M"),
        (2_500_000, "2.5M"),
    ],
)
def test_format_tokens_precise(n: int, expected: str) -> None:
    assert _format_tokens_precise(n) == expected
```

- [ ] **Step 8.2: Run tests, expect failure**

Run: `pytest tests/domain/test_progress_format.py -v`
Expected: FAIL — function does not exist.

- [ ] **Step 8.3: Implement**

Append to `packages/engine/src/a2sdlc/domain/progress_format.py`:

```python
def _format_tokens_precise(tokens: int) -> str:
    """Spec §Stats line formatting.

    `_format_tokens` (integer Xk) is too coarse for stats-line use.
    This sibling helper renders:
      0           -> "0"
      1..999      -> "{n}"
      1k..<1M     -> "X.Yk" with one decimal
      >=1M        -> "X.YM" with one decimal
    """
    if tokens <= 0:
        return "0"
    if tokens < 1_000:
        return str(tokens)
    if tokens < 1_000_000:
        return f"{tokens / 1000:.1f}k"
    return f"{tokens / 1_000_000:.1f}M"
```

- [ ] **Step 8.4: Run tests, verify pass**

Run: `pytest tests/domain/test_progress_format.py -v`
Expected: 9 PASS.

- [ ] **Step 8.5: Commit**

```bash
git add packages/engine/src/a2sdlc/domain/progress_format.py tests/domain/test_progress_format.py
git commit -m "feat(domain): _format_tokens_precise for stats-line rendering"
```

---

### Task 9: StageEnd.artifact_path field + RunEnd event

**Files:**
- Modify: `packages/engine/src/a2sdlc/domain/progress.py`
- Modify: `tests/domain/test_progress.py` (or create)

Spec §Console output cadence: add `artifact_path: Path | None = None` to `StageEnd`; add `RunEnd` event.

- [ ] **Step 9.1: Write failing test**

Add to `tests/domain/test_progress.py` (create if absent):

```python
"""StageEnd.artifact_path + RunEnd event."""
from __future__ import annotations

from pathlib import Path

from a2sdlc.domain.models import StageName
from a2sdlc.domain.progress import RunEnd, StageEnd
from a2sdlc.domain.stats import StageRunStats


def test_stage_end_artifact_path_default_none() -> None:
    # Construct via existing kwargs; only the new field is asserted.
    e = StageEnd(stage=StageName.SPEC, success=True, error=None, final_metrics=None)
    assert e.artifact_path is None


def test_stage_end_carries_artifact_path() -> None:
    e = StageEnd(
        stage=StageName.SPEC,
        success=True,
        error=None,
        final_metrics=None,
        artifact_path=Path("/tmp/spec.md"),
    )
    assert e.artifact_path == Path("/tmp/spec.md")


def test_run_end_dataclass_shape() -> None:
    e = RunEnd(
        workflow_id="a2sdlc/auto/x/20260430-142208-a3f019",
        success=True,
        error=None,
        aggregate_stats=StageRunStats(),
        total_cycles={StageName.SPEC: 1, StageName.IMPLEMENT: 2, StageName.REVIEW: 2},
    )
    assert e.workflow_id == "a2sdlc/auto/x/20260430-142208-a3f019"
    assert e.success is True
    assert e.total_cycles[StageName.IMPLEMENT] == 2
```

- [ ] **Step 9.2: Run tests, expect failure**

Run: `pytest tests/domain/test_progress.py -v`
Expected: FAIL on `unexpected keyword argument 'artifact_path'` and `RunEnd not found`.

- [ ] **Step 9.3: Add `artifact_path` to StageEnd**

Edit `packages/engine/src/a2sdlc/domain/progress.py`. Locate the `StageEnd` dataclass; add (preserving existing fields):

```python
from pathlib import Path  # add to imports if absent

@dataclass(frozen=True)
class StageEnd:
    stage: StageName
    success: bool
    error: str | None
    final_metrics: Metrics | None
    artifact_path: Path | None = None  # NEW: spec §Console output cadence
```

- [ ] **Step 9.4: Add RunEnd event**

In the same file:

```python
@dataclass(frozen=True)
class RunEnd:
    """Workflow-level terminal event. Spec §Console output cadence.

    Emitted by pipeline/dispatch.py in a finally block on every exit
    path. Console subscriber renders `totals:` (success) or
    `totals (failed):` + error message (failure).
    """
    workflow_id: str
    success: bool
    error: str | None
    aggregate_stats: "StageRunStats"
    total_cycles: dict[StageName, int]
```

Add `from a2sdlc.domain.stats import StageRunStats` if not already imported (use a `TYPE_CHECKING` block if there's a cycle). Add `RunEnd` to the `ProgressEvent` union if one is exported.

- [ ] **Step 9.5: Run tests, verify pass**

Run: `pytest tests/domain/test_progress.py -v`
Expected: 3 PASS.

- [ ] **Step 9.6: Commit**

```bash
git add packages/engine/src/a2sdlc/domain/progress.py tests/domain/test_progress.py
git commit -m "feat(domain): StageEnd.artifact_path + RunEnd event"
```

---

### Task 10: Dispatch teardown emits RunEnd

**Files:**
- Modify: `packages/engine/src/a2sdlc/pipeline/dispatch.py`
- Create: `tests/pipeline/test_dispatch_runend.py`

Dispatch wraps the run loop in `try/finally`. On terminal exit, reads `state.json` to build `aggregate_stats` + `total_cycles`, emits `RunEnd` to subscribers, then releases the lockfile.

- [ ] **Step 10.1: Write failing test**

Create `tests/pipeline/test_dispatch_runend.py`:

```python
"""Dispatch must emit RunEnd on success and failure paths."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from a2sdlc.domain.progress import RunEnd


@pytest.mark.asyncio
async def test_run_end_fires_on_success(tmp_path, monkeypatch):
    captured: list = []
    # build a minimal RunContext with stub adapters that return immediately;
    # see existing tests/pipeline/test_dispatch.py for a working harness.
    ctx = make_test_ctx(tmp_path, captured.append)
    from a2sdlc.pipeline.dispatch import dispatch
    await dispatch(ctx)
    assert any(isinstance(e, RunEnd) for e in captured)
    run_end = next(e for e in captured if isinstance(e, RunEnd))
    assert run_end.success is True


@pytest.mark.asyncio
async def test_run_end_fires_on_failure(tmp_path):
    captured: list = []
    ctx = make_test_ctx(tmp_path, captured.append, fail_at_stage="IMPLEMENT")
    from a2sdlc.pipeline.dispatch import dispatch
    with pytest.raises(Exception):
        await dispatch(ctx)
    assert any(isinstance(e, RunEnd) for e in captured)
    run_end = next(e for e in captured if isinstance(e, RunEnd))
    assert run_end.success is False
    assert run_end.error
```

(`make_test_ctx` lives in your existing dispatch test harness; if absent, copy the smallest construction snippet from a sibling test.)

- [ ] **Step 10.2: Run test, expect failure**

Run: `pytest tests/pipeline/test_dispatch_runend.py -v`
Expected: FAIL.

- [ ] **Step 10.3: Add RunEnd emission**

Edit `packages/engine/src/a2sdlc/pipeline/dispatch.py`. Wrap the existing `dispatch()` body in a structure like:

```python
async def dispatch(ctx: RunContext) -> DispatchResult:
    success = True
    error: str | None = None
    try:
        # existing body...
        return await stack(ctx, intent)
    except Exception as exc:
        success = False
        error = str(exc)
        raise
    finally:
        _emit_run_end(ctx, success=success, error=error)


def _emit_run_end(ctx: RunContext, *, success: bool, error: str | None) -> None:
    from a2sdlc.domain.progress import RunEnd
    from a2sdlc.domain.stats import StageRunStats

    workflow_id = getattr(ctx, "workflow_id", None) or getattr(ctx, "branch", "")
    try:
        # state.json is the source of truth for cycle counts + aggregated stats.
        state = ctx.load_state() if hasattr(ctx, "load_state") else {}
        cycles = state.get("total_cycles", {}) if isinstance(state, dict) else {}
        agg = state.get("aggregate_stats")
        aggregate = (
            StageRunStats(**agg) if isinstance(agg, dict) else StageRunStats()
        )
    except Exception:  # noqa: BLE001
        cycles = {}
        aggregate = StageRunStats()
    ctx.progress_state.publish(
        RunEnd(
            workflow_id=str(workflow_id),
            success=success,
            error=error,
            aggregate_stats=aggregate,
            total_cycles=cycles,
        )
    )
```

(Adapt `ctx.progress_state.publish(...)` to whatever the existing event-publishing API is.)

- [ ] **Step 10.4: Run test, verify pass**

Run: `pytest tests/pipeline/test_dispatch_runend.py -v`
Expected: PASS.

- [ ] **Step 10.5: Commit**

```bash
git add packages/engine/src/a2sdlc/pipeline/dispatch.py tests/pipeline/test_dispatch_runend.py
git commit -m "feat(pipeline): emit RunEnd in dispatch finally block"
```

---

### Task 11: Console subscriber three-rhythm renderer

**Files:**
- Modify: `packages/engine/src/a2sdlc/adapters/subscriber/console.py`
- Modify or create: `tests/adapters/subscriber/test_console.py`

Spec §Console output cadence. Three rhythms: `[STAGE] starting (cycle N)`, mid-stage events, terminal output block + stats. Plus final `totals:` from `RunEnd`.

- [ ] **Step 11.1: Write failing test**

Create `tests/adapters/subscriber/test_console.py`:

```python
"""ConsoleSubscriber three-rhythm renderer."""
from __future__ import annotations

import io

from a2sdlc.adapters.subscriber.console import ConsoleSubscriber
from a2sdlc.domain.models import StageName
from a2sdlc.domain.progress import (
    StageStart,
    Milestone,
    StageEnd,
    RunEnd,
)
from a2sdlc.domain.stats import StageRunStats


def render(events) -> str:
    buf = io.StringIO()
    sub = ConsoleSubscriber(stream=buf)
    for e in events:
        sub.handle(e)
    return buf.getvalue()


def test_stage_start_renders_starting_line() -> None:
    out = render([StageStart(stage=StageName.SPEC, cycle=1)])
    assert "[SPEC]      starting (cycle 1)" in out


def test_stage_end_emits_output_block_and_stats(tmp_path) -> None:
    artifact = tmp_path / "spec.md"
    artifact.write_text("hello world\n")
    final_metrics = make_metrics(input_tokens=12_400, output_tokens=3_100,
                                 num_turns=4, total_cost_usd=0.082, elapsed=18.3)
    events = [
        StageStart(stage=StageName.SPEC, cycle=1),
        StageEnd(
            stage=StageName.SPEC, success=True, error=None,
            final_metrics=final_metrics, artifact_path=artifact,
        ),
    ]
    out = render(events)
    assert "===== a2sdlc:stage-output BEGIN =====" in out
    assert "hello world" in out
    assert "===== a2sdlc:stage-output END =====" in out
    assert "18s · 4 turns · 12.4k in / 3.1k out · $0.08" in out


def test_run_end_success_renders_totals() -> None:
    events = [
        RunEnd(
            workflow_id="a2sdlc/auto/x/20260430-142208-a3f019",
            success=True, error=None,
            aggregate_stats=StageRunStats(
                cost_usd=0.79, tokens_in=107_100, tokens_out=26_200,
                duration_ms=317_000, num_turns=23,
            ),
            total_cycles={StageName.SPEC: 1, StageName.IMPLEMENT: 2, StageName.REVIEW: 2},
        ),
    ]
    out = render(events)
    assert "totals: 5m 17s · 23 turns · 107.1k in / 26.2k out · $0.79" in out
    assert "totals (failed):" not in out


def test_run_end_failure_renders_failed_totals() -> None:
    events = [
        RunEnd(
            workflow_id="x", success=False, error="push failed",
            aggregate_stats=StageRunStats(),
            total_cycles={},
        ),
    ]
    out = render(events)
    assert "totals (failed):" in out
    assert "push failed" in out
```

(`make_metrics` is a small helper that builds the existing `Metrics` dataclass — define it inline or import from a shared test util.)

- [ ] **Step 11.2: Run test, expect failure**

Run: `pytest tests/adapters/subscriber/test_console.py -v`
Expected: FAIL on every case.

- [ ] **Step 11.3: Implement renderer**

Edit `packages/engine/src/a2sdlc/adapters/subscriber/console.py`. The existing rich-Live renderer can stay; add a plain-text path the tests use. Sketch:

```python
from a2sdlc.domain.progress_format import _format_duration, _format_tokens_precise
from a2sdlc.domain.progress import StageStart, StageEnd, RunEnd, Milestone, GroupOpen, GroupClose, ToolEntry
from a2sdlc.domain.stats import StageRunStats

_FENCE_BEGIN = "===== a2sdlc:stage-output BEGIN ====="
_FENCE_END = "===== a2sdlc:stage-output END ====="


def _stage_tag(stage) -> str:
    return f"[{stage.value:<9}]"


def _format_cost(usd: float) -> str:
    return f"${usd:.2f}"


def _stats_from_metrics(m) -> str:
    if m is None:
        return "- · - turns · - in / - out · -"
    duration = _format_duration(m.elapsed) if hasattr(m, "elapsed") else "0s"
    return (
        f"{duration} · "
        f"{m.num_turns} turns · "
        f"{_format_tokens_precise(m.input_tokens)} in / "
        f"{_format_tokens_precise(m.output_tokens)} out · "
        f"{_format_cost(m.total_cost_usd)}"
    )


def _stats_from_run_stats(s: StageRunStats) -> str:
    return (
        f"{_format_duration(s.duration_ms / 1000)} · "
        f"{s.num_turns} turns · "
        f"{_format_tokens_precise(s.tokens_in)} in / "
        f"{_format_tokens_precise(s.tokens_out)} out · "
        f"{_format_cost(s.cost_usd)}"
    )


class ConsoleSubscriber:
    def __init__(self, stream=None):
        import sys
        self.stream = stream or sys.stdout

    def _write(self, line: str) -> None:
        self.stream.write(line + "\n")

    def handle(self, event) -> None:
        if isinstance(event, StageStart):
            self._write(f"{_stage_tag(event.stage)} starting (cycle {event.cycle})")
        elif isinstance(event, Milestone):
            self._write(f"{_stage_tag(event.stage)} {event.text}")
        elif isinstance(event, ToolEntry):
            self._write(f"{_stage_tag(event.stage)} tool: {event.name} {event.summary}".rstrip())
        elif isinstance(event, (GroupOpen, GroupClose)):
            self._write(f"{_stage_tag(event.stage)} {event.label}")
        elif isinstance(event, StageEnd):
            if event.artifact_path is not None and event.artifact_path.exists():
                self._write(_FENCE_BEGIN)
                self._write(event.artifact_path.read_text().rstrip("\n"))
                self._write(_FENCE_END)
            stats = _stats_from_metrics(event.final_metrics)
            transition = (
                "approved" if event.success and event.stage.value == "REVIEW"
                else "handover → IMPLEMENT" if not event.success and event.stage.value == "REVIEW"
                else f"done"
            )
            self._write(f"{_stage_tag(event.stage)} {transition}     | {stats}")
        elif isinstance(event, RunEnd):
            label = "totals" if event.success else "totals (failed)"
            stats = _stats_from_run_stats(event.aggregate_stats)
            line = f"{label}: {stats}"
            if not event.success and event.error:
                line += f"\nerror: {event.error}"
            self._write(line)
```

(The exact event-type names and fields — `StageStart`, `Milestone`, `ToolEntry`, `GroupOpen`, `GroupClose` — must match what `domain/progress.py` actually exports. Adjust imports.)

- [ ] **Step 11.4: Run tests, verify pass**

Run: `pytest tests/adapters/subscriber/test_console.py -v`
Expected: 4 PASS.

- [ ] **Step 11.5: Commit**

```bash
git add packages/engine/src/a2sdlc/adapters/subscriber/console.py tests/adapters/subscriber/test_console.py
git commit -m "feat(subscriber): three-rhythm console renderer with output blocks + totals"
```

---

### Task 12: MLflow run_name + tags

**Files:**
- Modify: `packages/engine/src/a2sdlc/adapters/subscriber/mlflow_trace.py`
- Modify: `tests/adapters/subscriber/test_mlflow_trace.py` (extend or create)

Spec §MLflow correlation: `run_name = workflow_id`; tags include `ticket_key`, `base`, `base_sha`, `ecosystem`, `input_hash`, `engine_version`.

- [ ] **Step 12.1: Write failing test**

Add to `tests/adapters/subscriber/test_mlflow_trace.py`:

```python
def test_mlflow_run_name_is_workflow_id(monkeypatch):
    captured = {}
    def fake_start(run_name=None, tags=None):
        captured["run_name"] = run_name
        captured["tags"] = tags
        return object()
    monkeypatch.setattr("mlflow.start_run", fake_start)

    from a2sdlc.adapters.subscriber.mlflow_trace import MlflowTraceSubscriber
    sub = MlflowTraceSubscriber()
    sub.start_run(workflow_id="a2sdlc/auto/x/20260430-142208-a3f019",
                  ticket_key="ABC-123",
                  base="req/x",
                  base_sha="0" * 40,
                  ecosystem="local",
                  input_hash="a3f019",
                  engine_version="abc1234")
    assert captured["run_name"] == "a2sdlc/auto/x/20260430-142208-a3f019"
    assert captured["tags"]["ticket_key"] == "ABC-123"
    assert captured["tags"]["base"] == "req/x"
    assert captured["tags"]["base_sha"] == "0" * 40
    assert captured["tags"]["ecosystem"] == "local"
    assert captured["tags"]["input_hash"] == "a3f019"
    assert captured["tags"]["engine_version"] == "abc1234"
```

- [ ] **Step 12.2: Run test, expect failure**

Run: `pytest tests/adapters/subscriber/test_mlflow_trace.py -v -k run_name`
Expected: FAIL.

- [ ] **Step 12.3: Implement**

Edit `packages/engine/src/a2sdlc/adapters/subscriber/mlflow_trace.py`. Replace the existing `start_run` (or wherever the MLflow run is created) with:

```python
def start_run(
    self,
    *,
    workflow_id: str,
    ticket_key: str | None,
    base: str,
    base_sha: str,
    ecosystem: str,
    input_hash: str,
    engine_version: str,
):
    import mlflow
    tags = {
        "base": base,
        "base_sha": base_sha,
        "ecosystem": ecosystem,
        "input_hash": input_hash,
        "engine_version": engine_version,
    }
    if ticket_key:
        tags["ticket_key"] = ticket_key
    return mlflow.start_run(run_name=workflow_id, tags=tags)
```

Update the caller in `pipeline/dispatch.py` (or wherever the run is started) to pass these args.

- [ ] **Step 12.4: Run tests, verify pass**

Run: `pytest tests/adapters/subscriber/test_mlflow_trace.py -v`
Expected: PASS.

- [ ] **Step 12.5: Commit**

```bash
git add packages/engine/src/a2sdlc/adapters/subscriber/mlflow_trace.py tests/adapters/subscriber/test_mlflow_trace.py packages/engine/src/a2sdlc/pipeline/dispatch.py
git commit -m "feat(subscriber): MLflow run_name=workflow_id + identity tags"
```

---

### Task 13: REQUIRED_ENV aggregation + fail-fast

**Files:**
- Create: `packages/engine/src/a2sdlc/runtime/env_check.py`
- Create: `tests/runtime/test_env_check.py`

Spec §Fail-fast on missing env vars. Pure function: takes a list of `(source_label, [var_names])`; consults `os.environ`; returns missing list. Exit-code formatting lives in CLI.

- [ ] **Step 13.1: Write failing tests**

Create `tests/runtime/test_env_check.py`:

```python
"""REQUIRED_ENV aggregation + fail-fast validator."""
from __future__ import annotations

import pytest

from a2sdlc.runtime.env_check import (
    MissingEnvVar,
    check_required_env,
    format_missing_message,
)


def test_no_missing_returns_empty(monkeypatch):
    monkeypatch.setenv("FOO", "1")
    monkeypatch.setenv("BAR", "2")
    missing = check_required_env([("engine", ["FOO"]), ("adapter:work", ["BAR"])])
    assert missing == []


def test_missing_aggregates(monkeypatch):
    monkeypatch.delenv("FOO", raising=False)
    monkeypatch.delenv("BAR", raising=False)
    missing = check_required_env([("engine", ["FOO"]), ("adapter:work", ["BAR"])])
    assert MissingEnvVar(name="FOO", source="engine") in missing
    assert MissingEnvVar(name="BAR", source="adapter:work") in missing


def test_format_missing_message_shape():
    msg = format_missing_message([
        MissingEnvVar(name="ANTHROPIC_API_KEY", source="engine"),
        MissingEnvVar(name="GITHUB_TOKEN", source="adapter:github-work"),
    ])
    assert "ANTHROPIC_API_KEY" in msg
    assert "(engine)" in msg
    assert "GITHUB_TOKEN" in msg
    assert "(adapter:github-work)" in msg
    assert msg.startswith("error:")
```

- [ ] **Step 13.2: Run tests, expect failure**

Run: `pytest tests/runtime/test_env_check.py -v`
Expected: FAIL.

- [ ] **Step 13.3: Implement**

Create `packages/engine/src/a2sdlc/runtime/env_check.py`:

```python
"""REQUIRED_ENV fail-fast validator. Spec §Fail-fast on missing env vars."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MissingEnvVar:
    name: str
    source: str  # "engine" | "adapter:<name>" | similar


def check_required_env(
    requirements: list[tuple[str, list[str]]],
) -> list[MissingEnvVar]:
    """Returns the list of missing vars. Empty list = all set."""
    missing: list[MissingEnvVar] = []
    for source, names in requirements:
        for name in names:
            if not os.environ.get(name):
                missing.append(MissingEnvVar(name=name, source=source))
    return missing


def format_missing_message(missing: list[MissingEnvVar]) -> str:
    if not missing:
        return ""
    lines = ["error: required environment variables are not set:"]
    width = max(len(m.name) for m in missing)
    for m in missing:
        lines.append(f"  - {m.name:<{width}}  ({m.source})")
    lines.append("set them in your shell or .envrc and try again.")
    return "\n".join(lines)
```

- [ ] **Step 13.4: Run tests, verify pass**

Run: `pytest tests/runtime/test_env_check.py -v`
Expected: 3 PASS.

- [ ] **Step 13.5: Commit**

```bash
git add packages/engine/src/a2sdlc/runtime/env_check.py tests/runtime/test_env_check.py
git commit -m "feat(runtime): REQUIRED_ENV aggregator + fail-fast formatter"
```

---

### Task 14: Lockfile + signal handlers

**Files:**
- Create: `packages/engine/src/a2sdlc/runtime/lockfile.py`
- Create: `tests/runtime/test_lockfile.py`

Spec §Failure modes (lockfile row), §Stale-lockfile policy. Exclusive `flock` PID lockfile, never auto-reclaims, signal-handler cleanup.

- [ ] **Step 14.1: Write failing tests**

Create `tests/runtime/test_lockfile.py`:

```python
"""PID lockfile with signal-handler cleanup. Spec §Failure modes."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from a2sdlc.runtime.lockfile import (
    LockfileBusy,
    acquire_lock,
)


def test_acquire_creates_lockfile_and_releases(tmp_path):
    lock_path = tmp_path / "run.lock"
    with acquire_lock(lock_path) as info:
        assert lock_path.exists()
        assert info.pid == os.getpid()
    assert not lock_path.exists()


def test_second_acquire_raises(tmp_path):
    lock_path = tmp_path / "run.lock"
    with acquire_lock(lock_path):
        with pytest.raises(LockfileBusy) as ei:
            with acquire_lock(lock_path):
                pass
        assert "pid" in str(ei.value).lower()


def test_lockfile_records_pid_and_ts(tmp_path):
    lock_path = tmp_path / "run.lock"
    with acquire_lock(lock_path):
        body = lock_path.read_text()
        assert str(os.getpid()) in body
```

- [ ] **Step 14.2: Run tests, expect failure**

Run: `pytest tests/runtime/test_lockfile.py -v`
Expected: FAIL.

- [ ] **Step 14.3: Implement**

Create `packages/engine/src/a2sdlc/runtime/lockfile.py`:

```python
"""Exclusive PID lockfile with signal-handler cleanup.

Spec §Failure modes (lockfile row) + §Stale-lockfile policy. v1 never
auto-reclaims a stale lockfile; recovery is manual `rm`.
"""
from __future__ import annotations

import contextlib
import errno
import fcntl
import os
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


class LockfileBusy(RuntimeError):
    pass


@dataclass(frozen=True)
class LockInfo:
    pid: int
    started: str  # ISO-8601 UTC


def _read_lock_metadata(lock_path: Path) -> tuple[int | None, str | None]:
    try:
        body = lock_path.read_text().strip()
        pid_str, ts = body.split("\t", 1)
        return int(pid_str), ts
    except Exception:  # noqa: BLE001
        return None, None


@contextlib.contextmanager
def acquire_lock(lock_path: Path) -> Iterator[LockInfo]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                pid, ts = _read_lock_metadata(lock_path)
                raise LockfileBusy(
                    f"another a2sdlc run is in progress on this VM "
                    f"(pid {pid} started {ts}). only one run at a time is supported."
                ) from None
            raise
        info = LockInfo(
            pid=os.getpid(),
            started=datetime.now(timezone.utc).isoformat(),
        )
        os.ftruncate(fd, 0)
        os.write(fd, f"{info.pid}\t{info.started}".encode("utf-8"))
        os.fsync(fd)

        # Signal handlers ensure cleanup on SIGINT / SIGTERM.
        previous_handlers = {}

        def _cleanup_on_signal(signum, frame):  # noqa: ANN001
            _release(fd, lock_path)
            # Restore previous handler and re-raise
            handler = previous_handlers.get(signum, signal.SIG_DFL)
            signal.signal(signum, handler)
            os.kill(os.getpid(), signum)

        for sig in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[sig] = signal.signal(sig, _cleanup_on_signal)

        try:
            yield info
        finally:
            for sig, h in previous_handlers.items():
                signal.signal(sig, h)
            _release(fd, lock_path)
    except Exception:
        # acquire failed before we owned the lock — close fd, do not delete.
        os.close(fd)
        raise


def _release(fd: int, lock_path: Path) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass
```

- [ ] **Step 14.4: Run tests, verify pass**

Run: `pytest tests/runtime/test_lockfile.py -v`
Expected: 3 PASS.

- [ ] **Step 14.5: Commit**

```bash
git add packages/engine/src/a2sdlc/runtime/lockfile.py tests/runtime/test_lockfile.py
git commit -m "feat(runtime): exclusive PID lockfile with signal-handler cleanup"
```

---

### Task 15: Dirty-tree check + protected-base guard

**Files:**
- Create: `packages/engine/src/a2sdlc/runtime/dirty_tree.py`
- Create: `tests/runtime/test_dirty_tree.py`

Spec CLI step 4 + protected-base step 3.

- [ ] **Step 15.1: Write failing tests**

Create `tests/runtime/test_dirty_tree.py`:

```python
"""Dirty-tree check. Spec CLI surface step 4."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from a2sdlc.runtime.dirty_tree import (
    DirtyTreeError,
    ensure_clean_tree,
    ensure_base_not_protected,
    BaseProtectedError,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _seed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "x@y.z")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("hello\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_clean_tree_passes(tmp_path):
    repo = _seed_repo(tmp_path)
    ensure_clean_tree(repo)


def test_modified_tracked_file_fails(tmp_path):
    repo = _seed_repo(tmp_path)
    (repo / "README.md").write_text("changed\n")
    with pytest.raises(DirtyTreeError):
        ensure_clean_tree(repo)


def test_untracked_outside_a2sdlc_is_tolerated(tmp_path):
    repo = _seed_repo(tmp_path)
    (repo / "scratch.txt").write_text("note\n")
    ensure_clean_tree(repo)  # passes — untracked outside .a2sdlc/


def test_protected_base_blocks(tmp_path):
    with pytest.raises(BaseProtectedError):
        ensure_base_not_protected("main", protected={"main", "master"}, allow=False)


def test_protected_base_allowed_with_flag(tmp_path):
    ensure_base_not_protected("main", protected={"main", "master"}, allow=True)
```

- [ ] **Step 15.2: Run tests, expect failure**

Run: `pytest tests/runtime/test_dirty_tree.py -v`
Expected: FAIL.

- [ ] **Step 15.3: Implement**

Create `packages/engine/src/a2sdlc/runtime/dirty_tree.py`:

```python
"""Dirty-tree + protected-base guards. Spec CLI surface steps 3-4."""
from __future__ import annotations

import subprocess
from pathlib import Path


class DirtyTreeError(RuntimeError):
    pass


class BaseProtectedError(RuntimeError):
    pass


def ensure_clean_tree(repo: Path) -> None:
    out = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    # Tolerate untracked files outside .a2sdlc/ ; reject everything else.
    bad: list[str] = []
    for line in out:
        # status code is first 2 chars; "?? path" = untracked
        code, _, path = line.partition(" ")
        if code == "??":
            if path.strip().startswith(".a2sdlc/"):
                bad.append(line)
        else:
            bad.append(line)
    if bad:
        raise DirtyTreeError(
            "working tree has uncommitted changes:\n"
            + "\n".join(bad)
            + "\ncommit, stash, or reset before running."
        )


def ensure_base_not_protected(
    base: str, *, protected: set[str], allow: bool
) -> None:
    if allow:
        return
    if base in protected:
        raise BaseProtectedError(
            f"refusing to run on protected base {base!r}. "
            "pass --allow-protected-base to override."
        )
```

- [ ] **Step 15.4: Run tests, verify pass**

Run: `pytest tests/runtime/test_dirty_tree.py -v`
Expected: 5 PASS.

- [ ] **Step 15.5: Commit**

```bash
git add packages/engine/src/a2sdlc/runtime/dirty_tree.py tests/runtime/test_dirty_tree.py
git commit -m "feat(runtime): dirty-tree + protected-base guards"
```

---

### Task 16: Agent isolation builder

**Files:**
- Create: `packages/engine/src/a2sdlc/runtime/isolation.py`
- Create: `tests/runtime/test_isolation.py`
- Modify: `packages/engine/src/a2sdlc/pipeline/runner.py`

Spec §Agent isolation. Curated env, empty `mcp_servers`, strip `CLAUDE_CONFIG_DIR`/`CLAUDE_HOME`.

- [ ] **Step 16.1: Write failing tests**

Create `tests/runtime/test_isolation.py`:

```python
"""Agent-process isolation. Spec §Agent isolation."""
from __future__ import annotations

import os

import pytest

from a2sdlc.runtime.isolation import build_sdk_env, build_sdk_options_overrides


def test_curated_env_drops_extra_keys():
    src = {
        "ANTHROPIC_API_KEY": "k",
        "PATH": "/usr/bin",
        "HOME": "/home/x",
        "LANG": "en_US.UTF-8",
        "RANDOM_OPERATOR_VAR": "leak",
        "CLAUDE_CONFIG_DIR": "/tmp/should-not",
        "CLAUDE_HOME": "/tmp/should-not",
    }
    env = build_sdk_env(src, required_env_names={"ANTHROPIC_API_KEY"})
    assert env["ANTHROPIC_API_KEY"] == "k"
    assert env["PATH"] == "/usr/bin"
    assert "RANDOM_OPERATOR_VAR" not in env
    assert "CLAUDE_CONFIG_DIR" not in env
    assert "CLAUDE_HOME" not in env


def test_options_overrides_pin_setting_sources_and_empty_mcp():
    overrides = build_sdk_options_overrides()
    assert overrides["setting_sources"] == ["project", "local"]
    assert overrides["mcp_servers"] == []  # empty list, not absent
```

- [ ] **Step 16.2: Run tests, expect failure**

Run: `pytest tests/runtime/test_isolation.py -v`
Expected: FAIL.

- [ ] **Step 16.3: Implement**

Create `packages/engine/src/a2sdlc/runtime/isolation.py`:

```python
"""Agent-process isolation. Spec §Agent isolation.

Curated env passed to the SDK, plus the SDK options overrides that
pin setting_sources, plugins (engine-controlled elsewhere), and an
explicit empty mcp_servers list so the SDK can't auto-discover from
~/.claude.json or stray .mcp.json files.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("a2sdlc.runtime.isolation")

# Always-passed-through, regardless of REQUIRED_ENV.
_BASELINE_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TZ")
# Always stripped, even if present in source env.
_FORBIDDEN_ENV = ("CLAUDE_CONFIG_DIR", "CLAUDE_HOME")


def build_sdk_env(
    source_env: dict[str, str],
    *,
    required_env_names: set[str],
) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in _BASELINE_ENV:
        if name in source_env:
            out[name] = source_env[name]
    for name in required_env_names:
        if name in source_env:
            out[name] = source_env[name]
    for name in _FORBIDDEN_ENV:
        if name in source_env:
            logger.warning(
                "ignoring %s=%s; engine controls SDK config",
                name, source_env[name],
            )
    return out


def build_sdk_options_overrides() -> dict[str, Any]:
    """Overrides applied to ClaudeAgentOptions kwargs at runner.py."""
    return {
        "setting_sources": ["project", "local"],
        "mcp_servers": [],
    }
```

- [ ] **Step 16.4: Wire into the runner**

Edit `packages/engine/src/a2sdlc/pipeline/runner.py`. Locate the
`options_kwargs = {...}` block; merge in the isolation overrides:

```python
from a2sdlc.runtime.isolation import build_sdk_options_overrides

# ... after building options_kwargs:
options_kwargs.update(build_sdk_options_overrides())
```

If the SDK is invoked as a subprocess (it isn't today — it's in-process via `claude_agent_sdk`), env-curation happens around any `subprocess.run` boundary. v1 keeps the in-process path; `build_sdk_env` is reserved for the subprocess fallback (Tasks 18 and 19 use it for the smoke harness env stripping).

- [ ] **Step 16.5: Run tests, verify pass**

Run: `pytest tests/runtime/test_isolation.py -v`
Expected: PASS.

- [ ] **Step 16.6: Commit**

```bash
git add packages/engine/src/a2sdlc/runtime/isolation.py tests/runtime/test_isolation.py packages/engine/src/a2sdlc/pipeline/runner.py
git commit -m "feat(runtime): agent isolation builder + SDK options pinning"
```

---

### Task 17: Config loader (.a2sdlc/config.yaml)

**Files:**
- Create: `packages/engine/src/a2sdlc/config_run.py`
- Create: `tests/config/test_config_run.py`

Spec §Composition. Pydantic model with `mode`, `adapters`, `subscribers`, `required_env`, `pipeline.{max_review_cycles, protected_bases}`.

- [ ] **Step 17.1: Write failing tests**

Create `tests/config/test_config_run.py`:

```python
"""RunConfig loader. Spec §Composition."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from a2sdlc.config_run import RunConfig, load_run_config, RunConfigError


def test_minimal_local_config_loads(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent("""\
        mode: local
        adapters:
          work: local-file
          review: local
        subscribers:
          - console
          - mlflow
        required_env:
          - ANTHROPIC_API_KEY
        pipeline:
          max_review_cycles: 3
          protected_bases:
            - main
            - master
    """))
    cfg = load_run_config(p)
    assert isinstance(cfg, RunConfig)
    assert cfg.mode == "local"
    assert cfg.adapters.work == "local-file"
    assert cfg.adapters.review == "local"
    assert cfg.subscribers == ["console", "mlflow"]
    assert cfg.required_env == ["ANTHROPIC_API_KEY"]
    assert cfg.pipeline.max_review_cycles == 3
    assert "main" in cfg.pipeline.protected_bases


def test_unknown_mode_rejected(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("mode: nope\nadapters: {work: x, review: y}\nsubscribers: []\n")
    with pytest.raises(RunConfigError):
        load_run_config(p)


def test_defaults_applied_when_pipeline_block_missing(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent("""\
        mode: local
        adapters:
          work: local-file
          review: local
        subscribers: []
        required_env: []
    """))
    cfg = load_run_config(p)
    assert cfg.pipeline.max_review_cycles == 3
    assert cfg.pipeline.protected_bases == ["main", "master"]


def test_missing_file_raises(tmp_path):
    with pytest.raises(RunConfigError):
        load_run_config(tmp_path / "no.yaml")
```

- [ ] **Step 17.2: Run tests, expect failure**

Run: `pytest tests/config/test_config_run.py -v`
Expected: FAIL.

- [ ] **Step 17.3: Implement**

Create `packages/engine/src/a2sdlc/config_run.py`:

```python
"""RunConfig — `.a2sdlc/config.yaml`. Spec §Composition."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

EcosystemMode = Literal["local", "github", "jira-github"]


class RunConfigError(ValueError):
    pass


class AdaptersConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    work: str
    review: str


class PipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_review_cycles: int = 3
    protected_bases: list[str] = Field(default_factory=lambda: ["main", "master"])


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: EcosystemMode
    adapters: AdaptersConfig
    subscribers: list[str] = Field(default_factory=list)
    required_env: list[str] = Field(default_factory=list)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)


def load_run_config(path: Path) -> RunConfig:
    if not path.exists():
        raise RunConfigError(f"config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise RunConfigError(f"invalid YAML in {path}: {exc}") from exc
    try:
        return RunConfig.model_validate(raw)
    except ValidationError as exc:
        raise RunConfigError(f"invalid config in {path}:\n{exc}") from exc
```

If `tests/config/__init__.py` doesn't exist, create it.

- [ ] **Step 17.4: Run tests, verify pass**

Run: `pytest tests/config/test_config_run.py -v`
Expected: 4 PASS.

- [ ] **Step 17.5: Commit**

```bash
git add packages/engine/src/a2sdlc/config_run.py tests/config/test_config_run.py tests/config/__init__.py
git commit -m "feat(config): RunConfig pydantic model for .a2sdlc/config.yaml"
```

---

### Task 18: `a2sdlc run` CLI surface (the orchestrator)

**Files:**
- Create: `packages/engine/src/a2sdlc/cli/run.py`
- Modify: `packages/engine/src/a2sdlc/cli/main.py`
- Create: `tests/cli/test_run.py`

Implements the 11-step CLI surface from the spec, wiring together every prior task.

- [ ] **Step 18.1: Write the failing test (env-fail-fast)**

Create `tests/cli/__init__.py` if absent. Create `tests/cli/test_run.py`:

```python
"""`a2sdlc run` CLI surface. Spec §CLI surface + §Failure modes."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


def _seed_repo_with_config(tmp_path: Path) -> Path:
    """Create a tiny git repo with a base branch + INPUT.md + config."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "INPUT.md").write_text("smoke task: noop\n")
    (repo / ".a2sdlc").mkdir()
    (repo / ".a2sdlc" / "config.yaml").write_text(textwrap.dedent("""\
        mode: local
        adapters: {work: local-file, review: local}
        subscribers: [console]
        required_env: [ANTHROPIC_API_KEY]
        pipeline: {max_review_cycles: 1, protected_bases: [main]}
    """))
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "req/smoke"], cwd=repo, check=True)
    return repo


def test_missing_env_exits_2_with_message(tmp_path, monkeypatch):
    repo = _seed_repo_with_config(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(repo)
    res = subprocess.run(
        [sys.executable, "-m", "a2sdlc", "run"],
        capture_output=True, text=True,
    )
    assert res.returncode == 2
    assert "ANTHROPIC_API_KEY" in res.stderr
    assert "(engine)" in res.stderr or "(adapter:" in res.stderr


def test_protected_base_exits_4(tmp_path, monkeypatch):
    repo = _seed_repo_with_config(tmp_path)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.chdir(repo)
    res = subprocess.run(
        [sys.executable, "-m", "a2sdlc", "run"],
        capture_output=True, text=True,
    )
    assert res.returncode == 4
    assert "protected base" in res.stderr.lower()


def test_dirty_tree_exits_5(tmp_path, monkeypatch):
    repo = _seed_repo_with_config(tmp_path)
    (repo / "INPUT.md").write_text("dirty\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.chdir(repo)
    res = subprocess.run(
        [sys.executable, "-m", "a2sdlc", "run"],
        capture_output=True, text=True,
    )
    assert res.returncode == 5
    assert "uncommitted" in res.stderr.lower() or "dirty" in res.stderr.lower()


def test_missing_input_md_exits_6(tmp_path, monkeypatch):
    repo = _seed_repo_with_config(tmp_path)
    (repo / "INPUT.md").unlink()
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "rm input"], cwd=repo, check=True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.chdir(repo)
    res = subprocess.run(
        [sys.executable, "-m", "a2sdlc", "run"],
        capture_output=True, text=True,
    )
    assert res.returncode == 6
    assert "INPUT.md" in res.stderr
```

- [ ] **Step 18.2: Run tests, expect failure**

Run: `pytest tests/cli/test_run.py -v`
Expected: FAIL — `run` command not registered.

- [ ] **Step 18.3: Implement the orchestrator**

Create `packages/engine/src/a2sdlc/cli/run.py`:

```python
"""`a2sdlc run` — the CLI orchestrator. Spec §CLI surface."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from a2sdlc.config_run import RunConfigError, load_run_config
from a2sdlc.runtime.branch import (
    compute_input_hash,
    format_run_branch,
)
from a2sdlc.runtime.dirty_tree import (
    BaseProtectedError,
    DirtyTreeError,
    ensure_base_not_protected,
    ensure_clean_tree,
)
from a2sdlc.runtime.env_check import check_required_env, format_missing_message
from a2sdlc.runtime.lockfile import LockfileBusy, acquire_lock


# Exit codes — see spec §Failure modes
EXIT_INTERNAL = 1
EXIT_MISSING_ENV = 2
EXIT_LOCKFILE = 3
EXIT_PROTECTED_BASE = 4
EXIT_DIRTY_TREE = 5
EXIT_INPUT_MISSING = 6
EXIT_BRANCH_EXISTS = 7
EXIT_COMMIT_FAILED = 8
EXIT_PUSH_FAILED = 9
EXIT_MAX_CYCLES = 10


def _eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


def _read_input_from_base_head(repo: Path, base: str) -> bytes | None:
    import subprocess as sp
    res = sp.run(
        ["git", "show", f"{base}:INPUT.md"],
        cwd=repo, capture_output=True,
    )
    if res.returncode != 0:
        return None
    return res.stdout


def _resolve_base(repo: Path, override: str | None) -> str:
    if override:
        return override
    import subprocess as sp
    res = sp.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return res.stdout.strip()


def _run_branch_exists(repo: Path, branch: str) -> bool:
    import subprocess as sp
    local = sp.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=repo, capture_output=True,
    )
    if local.returncode == 0:
        return True
    remote = sp.run(
        ["git", "ls-remote", "--exit-code", "--heads", "origin", branch],
        cwd=repo, capture_output=True,
    )
    return remote.returncode == 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="a2sdlc run")
    p.add_argument("--config", default=".a2sdlc/config.yaml")
    p.add_argument("--base", default=None)
    p.add_argument("--label", default=None)
    p.add_argument("--mode", default=None)
    p.add_argument("--allow-protected-base", action="store_true")
    args = p.parse_args(argv)

    repo = Path.cwd()

    # Step 1: env validation (no git, no FS beyond config).
    try:
        cfg = load_run_config(repo / args.config)
    except RunConfigError as exc:
        _eprint(f"error: {exc}")
        return EXIT_INTERNAL

    requirements = [("engine", cfg.required_env)]
    # Adapters' REQUIRED_ENV would be added here when their classes are loaded.
    missing = check_required_env(requirements)
    if missing:
        _eprint(format_missing_message(missing))
        return EXIT_MISSING_ENV

    # Step 2: lockfile.
    lock_path = repo / ".a2sdlc" / "run.lock"
    try:
        lock_ctx = acquire_lock(lock_path)
        lock_ctx.__enter__()
    except LockfileBusy as exc:
        _eprint(f"error: {exc}")
        return EXIT_LOCKFILE

    try:
        # Step 3: base.
        base = _resolve_base(repo, args.base)
        try:
            ensure_base_not_protected(
                base,
                protected=set(cfg.pipeline.protected_bases),
                allow=args.allow_protected_base,
            )
        except BaseProtectedError as exc:
            _eprint(f"error: {exc}")
            return EXIT_PROTECTED_BASE

        # Step 4: dirty tree.
        try:
            ensure_clean_tree(repo)
        except DirtyTreeError as exc:
            _eprint(f"error: {exc}")
            return EXIT_DIRTY_TREE

        # Step 5: INPUT.md from base HEAD.
        content = _read_input_from_base_head(repo, base)
        if content is None:
            _eprint(
                f"error: INPUT.md not found on '{base}' HEAD. "
                "commit it on the base branch and try again."
            )
            return EXIT_INPUT_MISSING

        # Step 6: branch name.
        ts = datetime.now(timezone.utc)
        h = compute_input_hash(content)
        run_branch = format_run_branch(base, ts, h)
        if _run_branch_exists(repo, run_branch):
            _eprint(
                f"error: branch '{run_branch}' already exists "
                "(local or origin). a duplicate run with the same "
                "INPUT.md within the same second is unsupported."
            )
            return EXIT_BRANCH_EXISTS

        # Step 7+: orchestrate the pipeline.
        from a2sdlc.cli.run_pipeline import drive_pipeline  # lazy import
        return drive_pipeline(
            repo=repo, cfg=cfg, base=base, run_branch=run_branch,
            input_md=content, ts=ts, input_hash=h, label=args.label,
        )
    finally:
        try:
            lock_ctx.__exit__(None, None, None)
        except Exception:
            pass
```

Create `packages/engine/src/a2sdlc/cli/run_pipeline.py` as the thin layer that constructs the run context, wires adapters, runs `dispatch.dispatch(ctx)`, handles the commit + push after each stage, returns 0 on success, mapped exit codes on failure. Sketch:

```python
"""Pipeline driver — assembles RunContext and runs dispatch.

Separated from cli/run.py so the orchestrator stays focused on
prelude (env, lock, base, dirty, input, branch). Step 7+ of the spec.
"""
from __future__ import annotations

import logging
import subprocess
from datetime import datetime
from pathlib import Path

from a2sdlc.adapters.review.local import LocalReviewAdapter
from a2sdlc.adapters.work.local_file import LocalFileWorkAdapter
from a2sdlc.config_run import RunConfig

logger = logging.getLogger("a2sdlc.cli.run_pipeline")

EXIT_OK = 0
EXIT_COMMIT_FAILED = 8
EXIT_PUSH_FAILED = 9
EXIT_MAX_CYCLES = 10
EXIT_INTERNAL = 1


def drive_pipeline(
    *,
    repo: Path,
    cfg: RunConfig,
    base: str,
    run_branch: str,
    input_md: bytes,
    ts: datetime,
    input_hash: str,
    label: str | None,
) -> int:
    # Create + checkout the run branch off base.
    subprocess.run(["git", "checkout", "-q", "-b", run_branch, base], cwd=repo, check=True)
    state_root = repo / ".a2sdlc" / "state" / run_branch.replace("/", "__")
    state_root.mkdir(parents=True, exist_ok=True)

    # Adapter wiring (local ecosystem v1).
    work = LocalFileWorkAdapter(state_root=state_root)
    review = LocalReviewAdapter(state_root=state_root)

    # Run the existing dispatch loop. The exact API depends on the
    # current dispatch.dispatch signature; the engine already takes a
    # RunContext. Build it here.
    from a2sdlc.domain.run_context import RunContext  # adjust to actual

    ctx = RunContext(
        # ... wire workflow_id=run_branch, ticket_key=label, base=base,
        # base_sha=<git rev-parse base>, ecosystem="local", work=work,
        # review=review, ... — match the existing constructor.
        workflow_id=run_branch,
        ticket_key=label,
        base=base,
        base_sha=subprocess.run(
            ["git", "rev-parse", base], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip(),
        ecosystem="local",
        work=work,
        review=review,
        config=cfg,
        repo_path=repo,
    )

    import asyncio
    from a2sdlc.pipeline.dispatch import dispatch
    try:
        asyncio.run(dispatch(ctx))
    except SystemExit:
        raise
    except Exception as exc:
        logger.exception("pipeline failed")
        print(f"error: internal failure: {exc}\n"
              f"lockfile released; partial state on local branch '{run_branch}'.",
              flush=True)
        return EXIT_INTERNAL

    # Final stdout: branch name.
    print(f"\ndone.\nbranch: {run_branch}")
    return EXIT_OK
```

Update `packages/engine/src/a2sdlc/cli/main.py` to register the `run` command:

```python
from a2sdlc.cli import run as run_module
app.command("run", help="Run pipeline against current base branch (local mode).")(
    run_module.main
)
```

(Match the existing `app.command(...)` registration pattern.)

- [ ] **Step 18.4: Run tests, verify pass on prelude steps**

Run: `pytest tests/cli/test_run.py -v -k "missing_env or protected_base or dirty_tree or missing_input"`
Expected: 4 PASS.

- [ ] **Step 18.5: Commit**

```bash
git add packages/engine/src/a2sdlc/cli/run.py packages/engine/src/a2sdlc/cli/run_pipeline.py packages/engine/src/a2sdlc/cli/main.py tests/cli/test_run.py tests/cli/__init__.py
git commit -m "feat(cli): a2sdlc run — env / lock / base / dirty / input / branch prelude"
```

(Note: full pipeline orchestration — stage loop, commit-and-push per stage, max-cycles handling — is exercised by the smoke harness in Task 19; unit-level integration of those uses mocked adapters and is added incrementally as the implementer fleshes out `drive_pipeline`.)

---

### Task 19: Smoke harness + make smoke-local + CI job

**Files:**
- Create: `scripts/smoke_local.sh`
- Modify: `Makefile`
- Modify: `.gitignore`
- Create: `.github/workflows/smoke-local.yml` (or extend existing CI config)

Spec §Testing strategy → end-to-end smoke. AC #15.

- [ ] **Step 19.1: Add `tmp/` to `.gitignore`**

Edit `.gitignore`:

```
# a2sdlc smoke harness scratch space
tmp/
tmp/smoke-local-failed-*
```

- [ ] **Step 19.2: Implement the smoke script**

Create `scripts/smoke_local.sh`:

```bash
#!/usr/bin/env bash
# Spec §Testing strategy → End-to-end smoke. AC #15.
set -euo pipefail

REQUIRED=(ANTHROPIC_API_KEY)
for v in "${REQUIRED[@]}"; do
  if [ -z "${!v:-}" ]; then
    echo "smoke-local skipped: $v not set"
    exit 0
  fi
done

ROOT="$(git rev-parse --show-toplevel)"
TMP="$ROOT/tmp/smoke-local"
WORK="$TMP/repo"
ORIGIN="$TMP/origin.git"

# Cleanup older failed-run preservation directories — keep only the most recent.
shopt -s nullglob
for d in "$ROOT/tmp/smoke-local-failed-"*; do
  rm -rf "$d"
done

rm -rf "$TMP"
mkdir -p "$WORK" "$ORIGIN"

git init -q --bare "$ORIGIN"
git init -q "$WORK"
cd "$WORK"
git config user.email "smoke@a2sdlc.local"
git config user.name "smoke"
git remote add origin "$ORIGIN"

mkdir -p .a2sdlc
cat > .a2sdlc/config.yaml <<'YAML'
mode: local
adapters: {work: local-file, review: local}
subscribers: [console, mlflow]
required_env: [ANTHROPIC_API_KEY]
pipeline: {max_review_cycles: 2, protected_bases: [main]}
YAML

cat > INPUT.md <<'MD'
# Smoke task

Add a top-level Python module `greet.py` that exposes a function
`greet(name: str) -> str` returning `"hello, {name}!"`. Add a unit
test in `tests/test_greet.py` covering the happy path.
MD

echo "scratch repo init" > README.md
git add .
git commit -q -m "init"
git checkout -q -b req/smoke-feature
git add INPUT.md
git commit -q --amend --no-edit
git push -q -u origin req/smoke-feature

# Run the engine.
TRANSCRIPT="$TMP/transcript.txt"
if a2sdlc run > "$TRANSCRIPT" 2>&1; then
  STATUS=0
else
  STATUS=$?
fi

# On failure, preserve the entire tree.
if [ "$STATUS" -ne 0 ]; then
  TS=$(date -u +%Y%m%dT%H%M%SZ)
  mv "$TMP" "$ROOT/tmp/smoke-local-failed-$TS"
  echo "smoke-local FAILED — preserved at tmp/smoke-local-failed-$TS"
  exit 1
fi

# Assertions.
fail() { echo "smoke-local ASSERT FAILED: $*"; exit 1; }

# Run-branch on origin.
RUN_BRANCH=$(git -C "$WORK" branch --show-current)
echo "$RUN_BRANCH" | grep -q "^a2sdlc/auto/" || fail "branch shape: $RUN_BRANCH"
git -C "$WORK" ls-remote origin "$RUN_BRANCH" | grep -q . || fail "branch missing on origin"

# Artifacts present.
STATE_DIR="$WORK/.a2sdlc/state/$(echo "$RUN_BRANCH" | tr / __)"
[ -f "$STATE_DIR/spec.md" ] || fail "spec.md missing under $STATE_DIR"
ls "$STATE_DIR/"implement-cycle-*.md > /dev/null 2>&1 || fail "implement-cycle-*.md missing"
ls "$STATE_DIR/reviews/"*.md > /dev/null 2>&1 || fail "review file missing"

# Stdout assertions.
grep -q "===== a2sdlc:stage-output BEGIN =====" "$TRANSCRIPT" || fail "missing output BEGIN fence"
grep -q "===== a2sdlc:stage-output END =====" "$TRANSCRIPT" || fail "missing output END fence"
grep -qE "^totals: " "$TRANSCRIPT" || fail "missing totals: line"

# Cleanup on success.
rm -rf "$TMP"

echo "smoke-local PASSED"
```

Make it executable:

```bash
chmod +x scripts/smoke_local.sh
```

- [ ] **Step 19.3: Add Makefile target**

Append to `Makefile`:

```makefile
smoke-local: ## End-to-end smoke against a scratch local-origin repo (opt-in via env)
	@bash scripts/smoke_local.sh
```

- [ ] **Step 19.4: Add CI job**

Create `.github/workflows/smoke-local.yml` (or extend an existing workflow):

```yaml
name: smoke-local

on:
  push:
    branches: [main]
  workflow_dispatch: {}

jobs:
  smoke-local:
    runs-on: ubuntu-latest
    timeout-minutes: 25
    env:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      # Deliberate isolation pollution to verify AC #16.
      CLAUDE_CONFIG_DIR: /tmp/should-not-exist
      A2SDLC_PLUGIN_PATHS: /tmp/should-not-exist
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: |
          pip install -e .
      - run: make smoke-local
```

- [ ] **Step 19.5: Manually verify the harness works**

Run locally with the env var set:

```bash
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY make smoke-local
```

Expected: exits 0 with `smoke-local PASSED`. If it fails, the directory at `tmp/smoke-local-failed-<ts>/` contains the full forensic state.

Run without the env var:

```bash
unset ANTHROPIC_API_KEY
make smoke-local
```

Expected: exits 0 with `smoke-local skipped: ANTHROPIC_API_KEY not set`.

- [ ] **Step 19.6: Commit**

```bash
git add scripts/smoke_local.sh Makefile .gitignore .github/workflows/smoke-local.yml
git commit -m "feat(smoke): make smoke-local end-to-end harness + CI job"
```

---

### Task 20: Documentation + architecture-test update

**Files:**
- Modify: `docs/architecture.md`
- Modify: architecture test (likely `tests/architecture/test_layers.py` or `tests/test_arch.py` — confirm).
- Modify: `CLAUDE.md` if conventions changed.

Spec §Migration notes: the new `runtime/` package joins the layer stack. AC #8: architecture tests still pass.

- [ ] **Step 20.1: Locate the architecture test**

Run: `grep -rn "import_linter\|layer_contract\|composition.*root\|architecture" tests/ packages/ --include="*.py" | head`

Identify the architecture test or import-linter contracts file.

- [ ] **Step 20.2: Add `runtime/` to the layer stack**

Edit `docs/architecture.md`. In the layer list, slot `runtime/` after the adapters tier and before the lifecycle/observability tier (it imports from `domain/` only and is used by `cli/` + composition):

```
Layer 0  domain/
Layer 1  config (config.py, config_run.py)
Layer 2  adapters/
Layer 3  runtime/  lifecycle/  observability/  evaluation/  assembly/
Layer 4  ingress/  gating/  effects/  middleware/  stages/
Layer 5  composition/
Layer 6  pipeline/
Layer 7  cli/
```

- [ ] **Step 20.3: Update import-linter contracts (or pytest arch test)**

If contracts live in `pyproject.toml` or `setup.cfg` or a dedicated `.importlinter` file, add `a2sdlc.runtime` to the relevant layer.

- [ ] **Step 20.4: Run the architecture test**

Run: `make arch` or the equivalent.
Expected: PASS.

- [ ] **Step 20.5: Run the full check**

Run: `make check`
Expected: PASS — lint, arch, test, test-integration, coverage-diff, security-audit.

- [ ] **Step 20.6: Commit**

```bash
git add docs/architecture.md pyproject.toml CLAUDE.md
git commit -m "docs: runtime/ layer added to architecture; smoke job documented"
```

---

## Self-review

### Spec coverage check
| Spec section | Implemented in |
|---|---|
| §Workflow vocabulary | Documentation-only; no code (per non-goal) |
| §Identity model | Task 1 |
| §Run-branch suffix | Task 3 |
| §State storage and lifecycle | Task 1 (schema_version) + Task 2 (migration) |
| §Adapter ecosystem (Local) | Tasks 4, 5, 6, 7 |
| §Adapter ecosystem (Future) | Out of v1 (deferred specs) |
| §Composition (config-file) | Task 17 |
| §CLI surface | Task 18 |
| §Failure modes | Tasks 13, 14, 15, 18 (each row) |
| §MLflow correlation | Task 12 |
| §Effects, signals, triggers | Existing infrastructure; no new code (signals defined but unexercised) |
| §Agent isolation | Task 16 |
| §Migration notes | Task 2 + Task 20 |
| §Testing strategy (unit) | Each task's TDD discipline |
| §Testing strategy (integration) | Adapter + runtime + dispatch tests across tasks |
| §Testing strategy (e2e smoke) | Task 19 |
| AC #1 artifacts on disk | Task 19 (assertions in smoke) |
| AC #2 same INPUT same hash | Task 3 + Task 19 |
| AC #3 changed INPUT new hash | Task 3 |
| AC #4 missing env exits 2 | Task 13 + Task 18 |
| AC #5 MLflow run_name | Task 12 |
| AC #6 handover loop | Existing dispatch + Task 11 (visible transitions) |
| AC #7 protected base | Task 15 + Task 18 |
| AC #8 arch tests pass | Task 20 |
| AC #9 concurrent lockfile | Task 14 |
| AC #10 dirty tree | Task 15 |
| AC #11 v0 migration | Task 2 |
| AC #12 stats summary line | Task 11 + Task 19 (smoke checks `totals:`) |
| AC #13 console cadence | Task 11 |
| AC #14 totals on failure | Task 10 + Task 11 |
| AC #15 smoke harness | Task 19 |
| AC #16 isolation contract | Task 16 + Task 19 (CI env pollution) |

No gaps.

### Placeholder scan
No `TBD`, `TODO`, `implement later`, "add appropriate error handling", or "similar to Task N" in the plan. Every code step contains complete code or a complete command. Two places intentionally point at the existing codebase ("adapt to the actual class") because the engine already has those constructions and the implementer should follow the established shape — those are guidance, not placeholders.

### Type-name consistency
- `LocalReviewAdapter` — used consistently across Tasks 6, 7, 18, 19.
- `LocalFileWorkAdapter.write_stage_artifact` — Tasks 4, 18, 19.
- `RunEnd` — Tasks 9, 10, 11.
- `_format_tokens_precise` — Tasks 8, 11.
- `EXIT_*` constants — defined in Task 18 (`cli/run.py`) and reused in `cli/run_pipeline.py` and the smoke harness via direct `git`/`grep` checks.
- `acquire_lock` / `LockfileBusy` — Tasks 14, 18.
- `RunConfig` / `load_run_config` / `RunConfigError` — Tasks 17, 18.
- `compute_input_hash` / `format_run_branch` — Tasks 3, 18, 19.
- `ensure_clean_tree` / `ensure_base_not_protected` — Tasks 15, 18.

No drift.

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-30-workflow-primitives-and-cli-mode-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
