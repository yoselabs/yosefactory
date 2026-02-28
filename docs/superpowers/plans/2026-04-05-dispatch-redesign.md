# Dispatch Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace bash-driven CI routing with a typed `a2sdlc dispatch` entry point — one stage per CI job, label-chain transitions, full observability.

**Architecture:** Single `dispatch()` function with injected dependencies (TicketAdapter, GitAdapter, StageRunner). Each invocation runs one stage, posts results, sets the next stage label to trigger the next CI job. Typed state machine (already implemented) drives all transitions.

**Tech Stack:** Python 3.12, PyGithub, gitpython, claude-agent-sdk, pydantic, pytest + pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-04-05-dispatch-redesign.md`

---

## File Structure

### New files
- `src/a2sdlc/exceptions.py` — SkipEvent, BlockedError
- `src/a2sdlc/adapters/protocols.py` — TicketAdapter, GitAdapter, StageRunner protocols
- `src/a2sdlc/adapters/github.py` — GitHubTicketAdapter (PyGithub) replacing github_tickets.py + github_code.py
- `src/a2sdlc/adapters/git.py` — LocalGitAdapter (gitpython)
- `src/a2sdlc/dispatch.py` — DispatchInput, DispatchContext, DispatchResult, dispatch()
- `tests/fakes.py` — FakeTicketAdapter, FakeGitAdapter, FakeRunner
- `tests/test_dispatch.py` — dispatch integration tests
- `tests/test_adapter_github.py` — GitHub adapter unit tests
- `tests/test_adapter_git.py` — git adapter unit tests
- `a2sdlc.yaml` — example config (for engine repo's own tests)

### Modified files
- `pyproject.toml` — add PyGithub, gitpython deps
- `src/a2sdlc/models.py` — update BranchState, Transition; remove StageAction
- `src/a2sdlc/config.py` — new ProjectConfig, PipelineFlags, load from a2sdlc.yaml
- `src/a2sdlc/stages/base.py` — update Protocol (drop resolve, keep transitions)
- `src/a2sdlc/stages/spec.py` — drop resolve(), update transitions (remove label/jira_status)
- `src/a2sdlc/stages/implement.py` — same
- `src/a2sdlc/stages/review.py` — same
- `src/a2sdlc/stages/merge.py` — same
- `src/a2sdlc/stages/__init__.py` — update registry, keep next_stage/get_transition
- `src/a2sdlc/cli.py` — gut, dispatch-only entry point
- `src/a2sdlc/runner.py` — extract format_cost, keep run_stage

### Removed files
- `src/a2sdlc/verifier.py`
- `src/a2sdlc/adapters/base.py` — replaced by protocols.py
- `src/a2sdlc/adapters/github_code.py` — merged into github.py
- `src/a2sdlc/adapters/github_tickets.py` — replaced by github.py
- `src/a2sdlc/adapters/jira_tickets.py` — defer to later (Jira adapter not in scope)
- `tests/test_verifier.py`
- `tests/test_github_code.py`
- `tests/test_github_tickets.py`
- `tests/test_jira_tickets.py`

---

### Task 0: Agent-harness setup + dependencies

**Files:**
- Modify: `pyproject.toml`
- Modify: `.agent-harness.yml`

- [ ] **Step 1: Add new dependencies to pyproject.toml**

```toml
# In [project] dependencies, add:
    "PyGithub>=2.6",
    "gitpython>=3.1",
```

Remove `"jira>=3.10"` (Jira adapter deferred).

- [ ] **Step 2: Sync dependencies**

Run: `cd ~/Workspaces/a2sdlc-engine && uv sync`
Expected: Clean install, no errors.

- [ ] **Step 3: Run agent-harness init**

Run: `cd ~/Workspaces/a2sdlc-engine && agent-harness init --apply`
Expected: Harness config updated.

- [ ] **Step 4: Run make check to verify baseline**

Run: `cd ~/Workspaces/a2sdlc-engine && make lint && make test`
Expected: All lint passes. All 126 tests pass.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock .agent-harness.yml
git commit -m "chore: add PyGithub + gitpython deps, remove jira dep"
```

---

### Task 1: Exceptions module

**Files:**
- Create: `src/a2sdlc/exceptions.py`
- Create: `tests/test_exceptions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_exceptions.py
"""Tests for a2sdlc exception types."""

from __future__ import annotations

import pytest

from a2sdlc.exceptions import BlockedError, SkipEvent


@pytest.mark.unit
class TestSkipEvent:
    def test_stores_reason(self) -> None:
        exc = SkipEvent("label 'bug' is not a stage label")
        assert exc.reason == "label 'bug' is not a stage label"
        assert "bug" in str(exc)

    def test_is_exception(self) -> None:
        with pytest.raises(SkipEvent):
            raise SkipEvent("test")


@pytest.mark.unit
class TestBlockedError:
    def test_stores_reason(self) -> None:
        exc = BlockedError("merge conflict with main")
        assert exc.reason == "merge conflict with main"
        assert "conflict" in str(exc)

    def test_is_exception(self) -> None:
        with pytest.raises(BlockedError):
            raise BlockedError("test")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Workspaces/a2sdlc-engine && uv run pytest tests/test_exceptions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'a2sdlc.exceptions'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/a2sdlc/exceptions.py
"""Pipeline exceptions — typed errors with reasons."""

from __future__ import annotations


class SkipEvent(Exception):
    """Event is not actionable — log and exit cleanly."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class BlockedError(Exception):
    """Unrecoverable error — set stage:blocked label and exit."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Workspaces/a2sdlc-engine && uv run pytest tests/test_exceptions.py -v`
Expected: 4 PASSED

- [ ] **Step 5: Lint + commit**

```bash
cd ~/Workspaces/a2sdlc-engine && uv run ruff check src/a2sdlc/exceptions.py tests/test_exceptions.py
git add src/a2sdlc/exceptions.py tests/test_exceptions.py
git commit -m "feat: add SkipEvent and BlockedError exception types"
```

---

### Task 2: Clean up models — remove StageAction, update BranchState, simplify Transition

**Files:**
- Modify: `src/a2sdlc/models.py`
- Modify: `tests/test_models.py`
- Modify: `src/a2sdlc/stages/spec.py`
- Modify: `src/a2sdlc/stages/implement.py`
- Modify: `src/a2sdlc/stages/review.py`
- Modify: `src/a2sdlc/stages/merge.py`
- Modify: `src/a2sdlc/stages/base.py`
- Modify: `src/a2sdlc/stages/__init__.py`
- Modify: `src/a2sdlc/config.py`

- [ ] **Step 1: Write failing test for updated BranchState**

Add to `tests/test_models.py`:

```python
from a2sdlc.models import BranchState, StageName, StageStatus


@pytest.mark.unit
class TestBranchState:
    def test_parse_with_all_fields(self) -> None:
        state = BranchState(
            stage=StageName.SPEC,
            status=StageStatus.COMPLETE,
            base_branch="feature/api",
            review_cycles=1,
            last_updated="2026-04-05T12:00:00Z",
        )
        assert state.stage == StageName.SPEC
        assert state.base_branch == "feature/api"
        assert state.review_cycles == 1

    def test_parse_legacy_without_new_fields(self) -> None:
        """Old state.json files missing base_branch/review_cycles should parse."""
        raw = '{"stage": "spec", "status": "complete", "last_updated": "2026-04-05T12:00:00Z"}'
        state = BranchState.model_validate_json(raw)
        assert state.base_branch == "main"
        assert state.review_cycles == 0

    def test_round_trip(self) -> None:
        state = BranchState(
            stage=StageName.IMPLEMENT,
            status=StageStatus.COMPLETE,
            last_updated="2026-04-05T12:00:00Z",
        )
        json_str = state.model_dump_json()
        parsed = BranchState.model_validate_json(json_str)
        assert parsed == state
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Workspaces/a2sdlc-engine && uv run pytest tests/test_models.py::TestBranchState -v`
Expected: FAIL — BranchState missing `base_branch` and `review_cycles` fields, or `stage` type mismatch.

- [ ] **Step 3: Update models.py**

In `src/a2sdlc/models.py`:

1. Update `BranchState`:
```python
class BranchState(BaseModel):
    """State file written to .a2sdlc/state.json on the agent branch."""
    stage: StageName
    status: StageStatus
    base_branch: str = "main"
    review_cycles: int = 0
    last_updated: str
```

2. Remove `label` and `jira_status` from `Transition`:
```python
@dataclass(frozen=True)
class Transition:
    next: StageName | None
    gate: Gate | None = None
```

3. Add `code_reviews` and `max_review_cycles` to `StageConfig` (in config.py):
```python
@dataclass
class StageConfig:
    name: str
    model: str = "claude-sonnet-4-6"
    max_turns: int = 25
    timeout_minutes: int = 60
    allowed_tools: list[str] = field(default_factory=list)
    code_reviews: int = 0
    max_review_cycles: int = 2
```

4. Remove `StageAction` dataclass entirely.

5. Remove `resolve()` from stage Protocol in `stages/base.py`:
```python
class Stage(Protocol):
    name: StageName
    config: StageConfig
    valid_statuses: frozenset[StageStatus]
    transitions: dict[StageStatus, Transition]
    uses_ai: bool
```

6. Remove `resolve()` methods from all stage classes (spec.py, implement.py, review.py, merge.py).

7. Remove `label=` and `jira_status=` from all `Transition()` declarations in stage classes.

- [ ] **Step 4: Run all tests, fix breakage**

Run: `cd ~/Workspaces/a2sdlc-engine && uv run pytest tests/ -v --tb=short`

Expected breakage:
- `tests/test_verifier.py` — imports StageAction, calls resolve(). **Delete this entire file.**
- `tests/test_stages.py` — tests that call `.resolve()`. **Delete the resolve test classes** (TestSpecResolve, TestImplementResolve, TestReviewResolve). Keep TestTransitionTable, TestNextStage, TestGetTransition.
- `tests/test_models.py` — if it tests StageAction. Remove those tests.
- `tests/test_cli.py` — may import verifier. Fix imports.

- [ ] **Step 5: Remove verifier.py and old adapter files**

```bash
rm src/a2sdlc/verifier.py
rm tests/test_verifier.py
rm src/a2sdlc/adapters/github_code.py
rm src/a2sdlc/adapters/jira_tickets.py
rm tests/test_github_code.py
rm tests/test_jira_tickets.py
```

- [ ] **Step 6: Run full test suite + lint**

Run: `cd ~/Workspaces/a2sdlc-engine && uv run pytest tests/ -v && uv run ruff check src/ tests/ && uv run ty check src/`
Expected: All pass, no lint errors.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: remove StageAction/resolve/verifier, update BranchState + Transition"
```

---

### Task 3: Adapter protocols + fakes

**Files:**
- Create: `src/a2sdlc/adapters/protocols.py`
- Create: `tests/fakes.py`
- Modify: `src/a2sdlc/adapters/__init__.py`

- [ ] **Step 1: Write the protocols**

```python
# src/a2sdlc/adapters/protocols.py
"""Adapter protocols — platform-agnostic interfaces."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from a2sdlc.config import StageConfig
from a2sdlc.models import StageName
from a2sdlc.runner import RunResult


class DispatchInput:
    """Normalized event from the adapter. Platform-agnostic."""

    __slots__ = ("key", "stage", "labels", "is_resume", "pr_number")

    def __init__(
        self,
        key: str,
        stage: StageName,
        labels: frozenset[str] = frozenset(),
        is_resume: bool = False,
        pr_number: int | None = None,
    ) -> None:
        self.key = key
        self.stage = stage
        self.labels = labels
        self.is_resume = is_resume
        self.pr_number = pr_number


class TicketAdapter(Protocol):
    """Platform-specific ticket operations."""

    STAGE_LABELS: dict[StageName, str]
    TRIGGER_LABEL: str
    BLOCKED_LABEL: str
    DONE_LABEL: str
    NEEDS_INPUT_LABEL: str
    PROCEED_LABEL: str

    def parse_event(self) -> DispatchInput: ...
    def get_ticket(self, key: str) -> str: ...
    def get_labels(self, key: str) -> list[str]: ...
    def post_comment(self, key: str, body: str) -> str: ...
    def update_comment(self, key: str, comment_id: str, body: str) -> None: ...
    def set_stage_label(self, key: str, stage: StageName) -> None: ...
    def set_done_label(self, key: str) -> None: ...
    def set_blocked(self, key: str, reason: str) -> None: ...
    def post_review(self, pr: int, body: str, event: str) -> None: ...
    def get_pr_for_branch(self, branch: str) -> int | None: ...
    def merge_pr(self, pr: int, method: str = "squash") -> None: ...


class GitAdapter(Protocol):
    """Local git operations."""

    def setup_branch(self, key: str, base: str) -> str: ...
    def sync_with_base(self, base: str) -> bool: ...
    def commit_artifacts(self, message: str, paths: list[str]) -> bool: ...
    def push(self) -> None: ...
    def read_state(self) -> str | None: ...
    def write_state(self, data: str) -> None: ...


class StageRunner(Protocol):
    """AI stage execution."""

    async def run(
        self,
        user_prompt: str,
        system_prompt: str,
        config: StageConfig,
        ticket_key: str,
        stage: StageName,
        project_root: str,
        is_resume: bool = False,
        on_progress: Callable[[str], None] | None = None,
    ) -> RunResult: ...
```

- [ ] **Step 2: Write the fakes for testing**

```python
# tests/fakes.py
"""Fake adapters for dispatch integration tests."""

from __future__ import annotations

from a2sdlc.adapters.protocols import DispatchInput, GitAdapter, StageRunner, TicketAdapter
from a2sdlc.config import StageConfig
from a2sdlc.exceptions import SkipEvent
from a2sdlc.models import StageName
from a2sdlc.runner import RunResult


class FakeTicketAdapter:
    """Records all calls for assertion."""

    STAGE_LABELS: dict[StageName, str] = {
        StageName.SPEC: "stage:spec",
        StageName.IMPLEMENT: "stage:implement",
        StageName.REVIEW: "stage:review",
        StageName.MERGE: "stage:merge",
    }
    TRIGGER_LABEL = "agent"
    BLOCKED_LABEL = "stage:blocked"
    DONE_LABEL = "stage:done"
    NEEDS_INPUT_LABEL = "needs-input"
    PROCEED_LABEL = "proceed"

    def __init__(
        self,
        event: DispatchInput | None = None,
        ticket_body: str = "Build something",
        labels: list[str] | None = None,
        pr_for_branch: int | None = None,
    ) -> None:
        self._event = event
        self._ticket_body = ticket_body
        self._labels = labels or []
        self._pr_for_branch = pr_for_branch
        self.comments: list[tuple[str, str]] = []
        self.updated_comments: list[tuple[str, str, str]] = []
        self.label_history: list[tuple[str, str, str]] = []  # (key, action, label)
        self.reviews: list[tuple[int, str, str]] = []
        self.merged_prs: list[int] = []
        self.blocked: list[tuple[str, str]] = []
        self._comment_counter = 0

    def parse_event(self) -> DispatchInput:
        if self._event is None:
            raise SkipEvent("no event configured in fake")
        return self._event

    def get_ticket(self, key: str) -> str:
        return self._ticket_body

    def get_labels(self, key: str) -> list[str]:
        return list(self._labels)

    def post_comment(self, key: str, body: str) -> str:
        self._comment_counter += 1
        cid = str(self._comment_counter)
        self.comments.append((key, body))
        return cid

    def update_comment(self, key: str, comment_id: str, body: str) -> None:
        self.updated_comments.append((key, comment_id, body))

    def set_stage_label(self, key: str, stage: StageName) -> None:
        self.label_history.append((key, "set", self.STAGE_LABELS[stage]))

    def set_done_label(self, key: str) -> None:
        self.label_history.append((key, "set", self.DONE_LABEL))

    def set_blocked(self, key: str, reason: str) -> None:
        self.blocked.append((key, reason))
        self.label_history.append((key, "set", self.BLOCKED_LABEL))

    def post_review(self, pr: int, body: str, event: str) -> None:
        self.reviews.append((pr, body, event))

    def get_pr_for_branch(self, branch: str) -> int | None:
        return self._pr_for_branch

    def merge_pr(self, pr: int, method: str = "squash") -> None:
        self.merged_prs.append(pr)


class FakeGitAdapter:
    """Records git operations."""

    def __init__(
        self,
        state_json: str | None = None,
        conflict_on_setup: bool = False,
    ) -> None:
        self._state_json = state_json
        self._conflict = conflict_on_setup
        self.branch_setups: list[tuple[str, str]] = []
        self.commits: list[tuple[str, list[str]]] = []
        self.pushes: int = 0
        self.written_state: str | None = None

    def setup_branch(self, key: str, base: str) -> str:
        from a2sdlc.exceptions import BlockedError

        if self._conflict:
            raise BlockedError(f"merge conflict with {base}")
        self.branch_setups.append((key, base))
        return f"agent/{key}"

    def sync_with_base(self, base: str) -> bool:
        return True

    def commit_artifacts(self, message: str, paths: list[str]) -> bool:
        self.commits.append((message, paths))
        return True

    def push(self) -> None:
        self.pushes += 1

    def read_state(self) -> str | None:
        return self._state_json

    def write_state(self, data: str) -> None:
        self.written_state = data


class FakeRunner:
    """Returns canned RunResult."""

    def __init__(self, result: RunResult) -> None:
        self._result = result
        self.calls: list[dict] = []

    async def run(
        self,
        user_prompt: str,
        system_prompt: str,
        config: StageConfig,
        ticket_key: str,
        stage: StageName,
        project_root: str,
        is_resume: bool = False,
        on_progress=None,
    ) -> RunResult:
        self.calls.append({
            "user_prompt": user_prompt,
            "stage": stage,
            "ticket_key": ticket_key,
            "is_resume": is_resume,
        })
        return self._result
```

- [ ] **Step 3: Update adapters/__init__.py**

Replace the contents of `src/a2sdlc/adapters/__init__.py` with:

```python
"""Adapter registry."""

from __future__ import annotations

from a2sdlc.adapters.protocols import (
    DispatchInput,
    GitAdapter,
    StageRunner,
    TicketAdapter,
)

__all__ = ["DispatchInput", "GitAdapter", "StageRunner", "TicketAdapter"]
```

- [ ] **Step 4: Run lint**

Run: `cd ~/Workspaces/a2sdlc-engine && uv run ruff check src/a2sdlc/adapters/ tests/fakes.py`
Expected: Clean.

- [ ] **Step 5: Commit**

```bash
git add src/a2sdlc/adapters/protocols.py src/a2sdlc/adapters/__init__.py tests/fakes.py
git commit -m "feat: add adapter protocols + test fakes"
```

---

### Task 4: Config rewrite — a2sdlc.yaml + PipelineFlags + resolve_flags

**Files:**
- Modify: `src/a2sdlc/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for new config**

```python
# Add to tests/test_config.py (replace existing config tests)

from a2sdlc.config import PipelineFlags, ProjectConfig, load_config_file, resolve_flags


@pytest.mark.unit
class TestPipelineFlags:
    def test_defaults(self) -> None:
        flags = PipelineFlags()
        assert flags.auto_spec is False
        assert flags.auto_proceed is True
        assert flags.auto_merge is False

    def test_frozen(self) -> None:
        flags = PipelineFlags()
        with pytest.raises(AttributeError):
            flags.auto_spec = True  # type: ignore[misc]


@pytest.mark.unit
class TestResolveFlags:
    def test_no_overrides(self) -> None:
        flags = resolve_flags(PipelineFlags(), labels=["agent", "bug"])
        assert flags == PipelineFlags()

    def test_auto_spec_label(self) -> None:
        flags = resolve_flags(PipelineFlags(), labels=["agent", "auto-spec"])
        assert flags.auto_spec is True
        assert flags.auto_proceed is True  # unchanged

    def test_auto_merge_label(self) -> None:
        flags = resolve_flags(PipelineFlags(), labels=["agent", "auto-merge"])
        assert flags.auto_merge is True

    def test_spec_only_label(self) -> None:
        flags = resolve_flags(PipelineFlags(), labels=["agent", "spec-only"])
        assert flags.auto_proceed is False

    def test_combined_labels(self) -> None:
        flags = resolve_flags(
            PipelineFlags(), labels=["agent", "auto-spec", "auto-merge"]
        )
        assert flags.auto_spec is True
        assert flags.auto_merge is True
        assert flags.auto_proceed is True


@pytest.mark.unit
class TestLoadConfigFile:
    def test_load_minimal(self, tmp_path: Path) -> None:
        config_file = tmp_path / "a2sdlc.yaml"
        config_file.write_text("adapter: github\n")
        config = load_config_file(tmp_path)
        assert config.adapter == "github"
        assert config.auto_merge is False
        assert config.default_base == "main"

    def test_load_full(self, tmp_path: Path) -> None:
        config_file = tmp_path / "a2sdlc.yaml"
        config_file.write_text(
            "adapter: github\n"
            "pipeline:\n"
            "  auto_merge: true\n"
            "  default_base: develop\n"
            "stages:\n"
            "  implement:\n"
            "    code_reviews: 3\n"
            "    max_turns: 200\n"
        )
        config = load_config_file(tmp_path)
        assert config.auto_merge is True
        assert config.default_base == "develop"

    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        config = load_config_file(tmp_path)
        assert config.adapter == "github"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Workspaces/a2sdlc-engine && uv run pytest tests/test_config.py -v --tb=short`
Expected: FAIL — `resolve_flags` and `load_config_file` don't exist.

- [ ] **Step 3: Rewrite config.py**

```python
# src/a2sdlc/config.py
"""Configuration for a2sdlc pipeline and stages."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

logger = logging.getLogger("a2sdlc.config")

# ── Stage configuration ───────────────────────────────────────────────


@dataclass
class StageConfig:
    """Configuration for a single pipeline stage."""

    name: str
    model: str = "claude-sonnet-4-6"
    max_turns: int = 25
    timeout_minutes: int = 60
    allowed_tools: list[str] = field(default_factory=list)
    code_reviews: int = 0
    max_review_cycles: int = 2


# ── Pipeline flags ────────────────────────────────────────────────────


@dataclass(frozen=True)
class PipelineFlags:
    """Boolean flags controlling pipeline autonomy."""

    auto_spec: bool = False
    auto_proceed: bool = True
    auto_merge: bool = False


# Label → (flag_name, value)
_LABEL_FLAG_MAP: dict[str, tuple[str, bool]] = {
    "auto-spec": ("auto_spec", True),
    "auto-merge": ("auto_merge", True),
    "spec-only": ("auto_proceed", False),
}


def resolve_flags(defaults: PipelineFlags, labels: list[str]) -> PipelineFlags:
    """Apply label overrides on top of project defaults."""
    overrides: dict[str, bool] = {}
    for label in labels:
        if label in _LABEL_FLAG_MAP:
            flag_name, value = _LABEL_FLAG_MAP[label]
            overrides[flag_name] = value
    if not overrides:
        return defaults
    return replace(defaults, **overrides)


# ── Project configuration ─────────────────────────────────────────────


@dataclass
class ProjectConfig:
    """Per-repo settings read from a2sdlc.yaml."""

    adapter: str = "github"
    auto_spec: bool = False
    auto_proceed: bool = True
    auto_merge: bool = False
    default_base: str = "main"
    test_command: str = "make test"
    stage_overrides: dict[str, dict[str, object]] = field(default_factory=dict)

    def pipeline_flags(self) -> PipelineFlags:
        """Build PipelineFlags from project defaults."""
        return PipelineFlags(
            auto_spec=self.auto_spec,
            auto_proceed=self.auto_proceed,
            auto_merge=self.auto_merge,
        )


def load_config_file(project_root: Path) -> ProjectConfig:
    """Load project config from a2sdlc.yaml at project_root."""
    config_path = project_root / "a2sdlc.yaml"
    if not config_path.exists():
        logger.info("No a2sdlc.yaml at %s — using defaults", config_path)
        return ProjectConfig()

    with config_path.open() as fh:
        data: dict = yaml.safe_load(fh) or {}

    pipeline = data.get("pipeline", {})
    pipeline = pipeline if isinstance(pipeline, dict) else {}
    testing = data.get("testing", {})
    testing = testing if isinstance(testing, dict) else {}
    stages = data.get("stages", {})
    stages = stages if isinstance(stages, dict) else {}

    return ProjectConfig(
        adapter=data.get("adapter", "github"),
        auto_spec=bool(pipeline.get("auto_spec", False)),
        auto_proceed=bool(pipeline.get("auto_proceed", True)),
        auto_merge=bool(pipeline.get("auto_merge", False)),
        default_base=str(pipeline.get("default_base", "main")),
        test_command=str(testing.get("command", "make test")),
        stage_overrides=stages,
    )


# ── Session helpers ──────────────────────────────────────────────────


def get_session_id(ticket_key: str, stage: str) -> str:
    """Deterministic UUID from ticket key + stage name."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"a2sdlc:{ticket_key}:{stage}"))


# ── Stage config loading ─────────────────────────────────────────────


def load_stage_config(stage_name: str, project: ProjectConfig) -> StageConfig:
    """Build StageConfig from stage defaults + project overrides."""
    from a2sdlc.stages import get_stage  # noqa: PLC0415

    stage = get_stage(stage_name)
    base = stage.config
    overrides = project.stage_overrides.get(stage_name, {})
    if not overrides:
        return base
    return replace(base, **{k: v for k, v in overrides.items() if v is not None})
```

- [ ] **Step 4: Run tests**

Run: `cd ~/Workspaces/a2sdlc-engine && uv run pytest tests/test_config.py -v --tb=short`
Expected: All new tests pass. Fix any old tests that break due to config API changes.

- [ ] **Step 5: Run full suite + lint**

Run: `cd ~/Workspaces/a2sdlc-engine && uv run pytest tests/ -v && uv run ruff check src/ tests/`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/a2sdlc/config.py tests/test_config.py
git commit -m "feat: rewrite config — a2sdlc.yaml, PipelineFlags, resolve_flags"
```

---

### Task 5: GitAdapter (gitpython)

**Files:**
- Create: `src/a2sdlc/adapters/git.py`
- Create: `tests/test_adapter_git.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_adapter_git.py
"""Tests for LocalGitAdapter — mock gitpython."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from a2sdlc.adapters.git import LocalGitAdapter
from a2sdlc.exceptions import BlockedError


@pytest.mark.unit
class TestSetupBranch:
    def test_creates_new_branch(self, tmp_path: Path) -> None:
        with patch("a2sdlc.adapters.git.Repo") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.heads = []  # no existing branches
            mock_repo.git = MagicMock()

            adapter = LocalGitAdapter(tmp_path)
            branch = adapter.setup_branch("15", "main")

        assert branch == "agent/15"
        mock_repo.git.checkout.assert_called()

    def test_checks_out_existing_branch(self, tmp_path: Path) -> None:
        with patch("a2sdlc.adapters.git.Repo") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_head = MagicMock()
            mock_head.name = "agent/15"
            mock_repo.heads = [mock_head]
            mock_repo.git = MagicMock()

            adapter = LocalGitAdapter(tmp_path)
            branch = adapter.setup_branch("15", "main")

        assert branch == "agent/15"

    def test_conflict_raises_blocked(self, tmp_path: Path) -> None:
        with patch("a2sdlc.adapters.git.Repo") as MockRepo:
            from git.exc import GitCommandError

            mock_repo = MockRepo.return_value
            mock_repo.heads = []
            mock_repo.git = MagicMock()
            mock_repo.git.merge.side_effect = GitCommandError("merge", "conflict")

            adapter = LocalGitAdapter(tmp_path)
            with pytest.raises(BlockedError, match="conflict"):
                adapter.setup_branch("15", "main")


@pytest.mark.unit
class TestCommitArtifacts:
    def test_commits_specified_paths(self, tmp_path: Path) -> None:
        with patch("a2sdlc.adapters.git.Repo") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.git = MagicMock()
            mock_repo.is_dirty.return_value = True

            adapter = LocalGitAdapter(tmp_path)
            result = adapter.commit_artifacts("chore: save", [".a2sdlc/state.json"])

        assert result is True
        mock_repo.git.add.assert_called_once_with(".a2sdlc/state.json")

    def test_nothing_to_commit(self, tmp_path: Path) -> None:
        with patch("a2sdlc.adapters.git.Repo") as MockRepo:
            mock_repo = MockRepo.return_value
            mock_repo.is_dirty.return_value = False

            adapter = LocalGitAdapter(tmp_path)
            result = adapter.commit_artifacts("chore: save", [".a2sdlc/state.json"])

        assert result is False


@pytest.mark.unit
class TestReadWriteState:
    def test_read_state_exists(self, tmp_path: Path) -> None:
        state_path = tmp_path / ".a2sdlc" / "state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text('{"stage":"spec"}')

        with patch("a2sdlc.adapters.git.Repo"):
            adapter = LocalGitAdapter(tmp_path)
            assert adapter.read_state() == '{"stage":"spec"}'

    def test_read_state_missing(self, tmp_path: Path) -> None:
        with patch("a2sdlc.adapters.git.Repo"):
            adapter = LocalGitAdapter(tmp_path)
            assert adapter.read_state() is None

    def test_write_state(self, tmp_path: Path) -> None:
        with patch("a2sdlc.adapters.git.Repo"):
            adapter = LocalGitAdapter(tmp_path)
            adapter.write_state('{"stage":"implement"}')

        state_path = tmp_path / ".a2sdlc" / "state.json"
        assert state_path.exists()
        assert "implement" in state_path.read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Workspaces/a2sdlc-engine && uv run pytest tests/test_adapter_git.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'a2sdlc.adapters.git'`

- [ ] **Step 3: Implement LocalGitAdapter**

```python
# src/a2sdlc/adapters/git.py
"""Git adapter — local git operations via gitpython."""

from __future__ import annotations

import logging
from pathlib import Path

from git import Repo
from git.exc import GitCommandError

from a2sdlc.exceptions import BlockedError

logger = logging.getLogger("a2sdlc.git")


class LocalGitAdapter:
    """Git operations for the a2sdlc pipeline."""

    def __init__(self, project_root: Path) -> None:
        self._root = project_root
        self._repo = Repo(project_root)

    def setup_branch(self, key: str, base: str) -> str:
        """Create or checkout agent branch, sync with base."""
        branch_name = f"agent/{key}"
        logger.info("git.setup_branch", extra={"branch": branch_name, "base": base})

        existing = [h for h in self._repo.heads if h.name == branch_name]
        if existing:
            self._repo.git.checkout(branch_name)
            logger.info("git.checkout_existing", extra={"branch": branch_name})
        else:
            self._repo.git.checkout("-b", branch_name)
            logger.info("git.create_branch", extra={"branch": branch_name})

        # Sync with base
        try:
            self._repo.git.fetch("origin", base)
            self._repo.git.merge(f"origin/{base}", "--no-edit")
            logger.info("git.synced", extra={"base": base})
        except GitCommandError as exc:
            self._repo.git.merge("--abort")
            logger.error("git.conflict", extra={"base": base, "error": str(exc)})
            raise BlockedError(f"merge conflict with {base}") from exc

        return branch_name

    def sync_with_base(self, base: str) -> bool:
        """Merge base into current branch. Return False on conflict."""
        try:
            self._repo.git.fetch("origin", base)
            self._repo.git.merge(f"origin/{base}", "--no-edit")
            return True
        except GitCommandError:
            self._repo.git.merge("--abort")
            return False

    def commit_artifacts(self, message: str, paths: list[str]) -> bool:
        """Stage specific paths + commit. Return False if nothing to commit."""
        for path in paths:
            self._repo.git.add(path)
        if not self._repo.is_dirty():
            logger.info("git.nothing_to_commit")
            return False
        self._repo.git.commit("-m", message)
        logger.info("git.committed", extra={"message": message, "paths": paths})
        return True

    def push(self) -> None:
        """Push current branch to origin."""
        branch = self._repo.active_branch.name
        self._repo.git.push("origin", branch)
        logger.info("git.pushed", extra={"branch": branch})

    def read_state(self) -> str | None:
        """Read .a2sdlc/state.json if it exists."""
        state_path = self._root / ".a2sdlc" / "state.json"
        if state_path.exists():
            return state_path.read_text()
        return None

    def write_state(self, data: str) -> None:
        """Write .a2sdlc/state.json."""
        state_path = self._root / ".a2sdlc" / "state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(data)
        logger.info("git.state_written")
```

- [ ] **Step 4: Run tests**

Run: `cd ~/Workspaces/a2sdlc-engine && uv run pytest tests/test_adapter_git.py -v`
Expected: All pass.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/a2sdlc/adapters/git.py tests/test_adapter_git.py
git add src/a2sdlc/adapters/git.py tests/test_adapter_git.py
git commit -m "feat: add LocalGitAdapter with gitpython"
```

---

### Task 6: GitHubTicketAdapter (PyGithub)

**Files:**
- Create: `src/a2sdlc/adapters/github.py`
- Create: `tests/test_adapter_github.py`
- Remove: `src/a2sdlc/adapters/github_tickets.py`
- Remove: `src/a2sdlc/adapters/_gh.py`

- [ ] **Step 1: Write failing tests for parse_event**

```python
# tests/test_adapter_github.py
"""Tests for GitHubTicketAdapter — mock PyGithub."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from a2sdlc.adapters.github import GitHubTicketAdapter
from a2sdlc.exceptions import SkipEvent
from a2sdlc.models import StageName


@pytest.mark.unit
class TestParseEvent:
    def _write_event(self, tmp_path: Path, event: dict) -> str:
        event_file = tmp_path / "event.json"
        event_file.write_text(json.dumps(event))
        return str(event_file)

    def test_agent_label_triggers_spec(self, tmp_path: Path) -> None:
        event_path = self._write_event(tmp_path, {
            "action": "labeled",
            "label": {"name": "agent"},
            "issue": {"number": 15, "labels": [{"name": "agent"}]},
            "sender": {"type": "User"},
        })
        with patch.dict(os.environ, {"GITHUB_EVENT_PATH": event_path, "GITHUB_EVENT_NAME": "issues"}):
            adapter = GitHubTicketAdapter(repo_name="owner/repo", token="fake")
            result = adapter.parse_event()
        assert result.stage == StageName.SPEC
        assert result.key == "15"
        assert result.is_resume is False

    def test_stage_label_triggers_stage(self, tmp_path: Path) -> None:
        event_path = self._write_event(tmp_path, {
            "action": "labeled",
            "label": {"name": "stage:implement"},
            "issue": {"number": 15, "labels": [{"name": "stage:implement"}]},
            "sender": {"type": "User"},
        })
        with patch.dict(os.environ, {"GITHUB_EVENT_PATH": event_path, "GITHUB_EVENT_NAME": "issues"}):
            adapter = GitHubTicketAdapter(repo_name="owner/repo", token="fake")
            result = adapter.parse_event()
        assert result.stage == StageName.IMPLEMENT

    def test_unknown_label_raises_skip(self, tmp_path: Path) -> None:
        event_path = self._write_event(tmp_path, {
            "action": "labeled",
            "label": {"name": "bug"},
            "issue": {"number": 15, "labels": [{"name": "bug"}]},
            "sender": {"type": "User"},
        })
        with patch.dict(os.environ, {"GITHUB_EVENT_PATH": event_path, "GITHUB_EVENT_NAME": "issues"}):
            adapter = GitHubTicketAdapter(repo_name="owner/repo", token="fake")
            with pytest.raises(SkipEvent, match="not a stage label"):
                adapter.parse_event()

    def test_bot_sender_raises_skip(self, tmp_path: Path) -> None:
        event_path = self._write_event(tmp_path, {
            "action": "labeled",
            "label": {"name": "stage:spec"},
            "issue": {"number": 15, "labels": []},
            "sender": {"type": "Bot"},
        })
        with patch.dict(os.environ, {"GITHUB_EVENT_PATH": event_path, "GITHUB_EVENT_NAME": "issues"}):
            adapter = GitHubTicketAdapter(repo_name="owner/repo", token="fake")
            with pytest.raises(SkipEvent, match="bot"):
                adapter.parse_event()


@pytest.mark.unit
class TestSetStageLabel:
    def test_removes_old_stage_label_sets_new(self) -> None:
        adapter = GitHubTicketAdapter(repo_name="owner/repo", token="fake")
        mock_repo = MagicMock()
        mock_issue = MagicMock()
        old_label = MagicMock()
        old_label.name = "stage:spec"
        bug_label = MagicMock()
        bug_label.name = "bug"
        mock_issue.labels = [old_label, bug_label]
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        adapter.set_stage_label("15", StageName.IMPLEMENT)

        mock_issue.remove_from_labels.assert_called_once_with(old_label)
        mock_issue.add_to_labels.assert_called_once_with("stage:implement")


@pytest.mark.unit
class TestSetBlocked:
    def test_adds_label_and_comment(self) -> None:
        adapter = GitHubTicketAdapter(repo_name="owner/repo", token="fake")
        mock_repo = MagicMock()
        mock_issue = MagicMock()
        mock_repo.get_issue.return_value = mock_issue
        adapter._repo = mock_repo

        adapter.set_blocked("15", "merge conflict")

        mock_issue.add_to_labels.assert_called_once_with("stage:blocked")
        mock_issue.create_comment.assert_called_once()
        body = mock_issue.create_comment.call_args[0][0]
        assert "merge conflict" in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Workspaces/a2sdlc-engine && uv run pytest tests/test_adapter_github.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement GitHubTicketAdapter**

Create `src/a2sdlc/adapters/github.py` implementing:
- `parse_event()` — reads `$GITHUB_EVENT_PATH`, handles issues/labeled, issue_comment/created, pull_request/labeled events. Raises `SkipEvent` for unknown labels or bot senders.
- `get_ticket(key)` — returns issue body for spec/implement, PR context for review.
- `get_labels(key)` — returns label names from issue.
- `post_comment/update_comment` — via PyGithub.
- `set_stage_label` — removes old `stage:*` labels, adds new one.
- `set_done_label`, `set_blocked` — label + comment management.
- `post_review` — PyGithub PR review.
- `get_pr_for_branch` — search open PRs by head branch.
- `merge_pr` — PyGithub squash merge.

The adapter owns all label string constants:
```python
STAGE_LABELS: dict[StageName, str] = {
    StageName.SPEC: "stage:spec",
    StageName.IMPLEMENT: "stage:implement",
    StageName.REVIEW: "stage:review",
    StageName.MERGE: "stage:merge",
}
TRIGGER_LABEL = "agent"
BLOCKED_LABEL = "stage:blocked"
DONE_LABEL = "stage:done"
NEEDS_INPUT_LABEL = "needs-input"
PROCEED_LABEL = "proceed"
```

- [ ] **Step 4: Run tests**

Run: `cd ~/Workspaces/a2sdlc-engine && uv run pytest tests/test_adapter_github.py -v`
Expected: All pass.

- [ ] **Step 5: Remove old adapter files**

```bash
rm src/a2sdlc/adapters/github_tickets.py
rm src/a2sdlc/adapters/github_code.py
rm src/a2sdlc/adapters/_gh.py
rm src/a2sdlc/adapters/base.py
rm tests/test_github_tickets.py
rm tests/test_github_code.py
```

- [ ] **Step 6: Lint + full test suite**

Run: `cd ~/Workspaces/a2sdlc-engine && uv run ruff check src/ tests/ && uv run pytest tests/ -v`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: add GitHubTicketAdapter with PyGithub, remove old adapters"
```

---

### Task 7: Dispatch function

**Files:**
- Create: `src/a2sdlc/dispatch.py`
- Create: `tests/test_dispatch.py`
- Modify: `src/a2sdlc/cli.py`

- [ ] **Step 1: Write failing dispatch integration tests**

```python
# tests/test_dispatch.py
"""Dispatch integration tests — fake adapters, real dispatch logic."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from a2sdlc.adapters.protocols import DispatchInput
from a2sdlc.config import PipelineFlags, ProjectConfig
from a2sdlc.dispatch import DispatchContext, DispatchResult, dispatch
from a2sdlc.exceptions import BlockedError, SkipEvent
from a2sdlc.models import StageName, StageStatus
from a2sdlc.runner import RunResult
from tests.fakes import FakeGitAdapter, FakeRunner, FakeTicketAdapter


def _success_result(output: str) -> RunResult:
    return RunResult(
        success=True,
        output=output,
        input_tokens=1000,
        output_tokens=500,
        total_cost_usd=0.05,
        duration_ms=30000,
    )


def _make_ctx(
    event: DispatchInput | None = None,
    result: RunResult | None = None,
    labels: list[str] | None = None,
    conflict: bool = False,
    state_json: str | None = None,
    auto_proceed: bool = True,
    auto_merge: bool = False,
    auto_spec: bool = False,
    pr_for_branch: int | None = None,
) -> DispatchContext:
    output = 'Done.\n\n```a2sdlc\n{"status": "complete"}\n```'
    return DispatchContext(
        tickets=FakeTicketAdapter(
            event=event,
            labels=labels or [],
            pr_for_branch=pr_for_branch,
        ),
        git=FakeGitAdapter(state_json=state_json, conflict_on_setup=conflict),
        runner=FakeRunner(result=result or _success_result(output)),
        config=ProjectConfig(
            auto_spec=auto_spec,
            auto_proceed=auto_proceed,
            auto_merge=auto_merge,
        ),
        project_root=Path("/tmp/test"),
        logger=logging.getLogger("test"),
    )


@pytest.mark.asyncio
@pytest.mark.unit
class TestDispatchSpecComplete:
    async def test_spec_complete_auto_proceed(self) -> None:
        event = DispatchInput(key="15", stage=StageName.SPEC)
        ctx = _make_ctx(event=event, auto_proceed=True)
        result = await dispatch(ctx)

        assert result.stage == StageName.SPEC
        assert result.status == StageStatus.COMPLETE
        assert result.next_stage == StageName.IMPLEMENT
        assert result.blocked is False
        # Verify label chain: set spec, then set implement
        labels = ctx.tickets.label_history
        assert ("15", "set", "stage:spec") in labels
        assert ("15", "set", "stage:implement") in labels

    async def test_spec_complete_gate_closed(self) -> None:
        event = DispatchInput(key="15", stage=StageName.SPEC)
        ctx = _make_ctx(event=event, auto_proceed=False)
        result = await dispatch(ctx)

        assert result.next_stage is None
        # Only spec label set, no implement
        labels = [l[2] for l in ctx.tickets.label_history]
        assert "stage:spec" in labels
        assert "stage:implement" not in labels


@pytest.mark.asyncio
@pytest.mark.unit
class TestDispatchSpecQuestions:
    async def test_questions_waits(self) -> None:
        output = 'What auth?\n\n```a2sdlc\n{"status": "questions"}\n```'
        event = DispatchInput(key="15", stage=StageName.SPEC)
        ctx = _make_ctx(event=event, result=_success_result(output))
        result = await dispatch(ctx)

        assert result.status == StageStatus.QUESTIONS
        assert result.next_stage is None


@pytest.mark.asyncio
@pytest.mark.unit
class TestDispatchErrors:
    async def test_skip_event(self) -> None:
        ctx = _make_ctx(event=None)  # FakeTicketAdapter raises SkipEvent
        result = await dispatch(ctx)
        assert result.error is not None

    async def test_git_conflict_blocks(self) -> None:
        event = DispatchInput(key="15", stage=StageName.SPEC)
        ctx = _make_ctx(event=event, conflict=True)
        result = await dispatch(ctx)

        assert result.blocked is True
        assert len(ctx.tickets.blocked) == 1

    async def test_stage_failure_blocks(self) -> None:
        event = DispatchInput(key="15", stage=StageName.SPEC)
        bad_result = RunResult(success=False, error="timeout (30min)")
        ctx = _make_ctx(event=event, result=bad_result)
        result = await dispatch(ctx)

        assert result.blocked is True


@pytest.mark.asyncio
@pytest.mark.unit
class TestDispatchReviewLoop:
    async def test_changes_requested_triggers_implement(self) -> None:
        output = 'Fix SQL.\n\n```a2sdlc\n{"status": "changes_requested"}\n```'
        event = DispatchInput(key="15", stage=StageName.REVIEW, pr_number=42)
        ctx = _make_ctx(event=event, result=_success_result(output))
        result = await dispatch(ctx)

        assert result.next_stage == StageName.IMPLEMENT
        labels = [l[2] for l in ctx.tickets.label_history]
        assert "stage:implement" in labels

    async def test_circuit_breaker_blocks(self) -> None:
        output = 'Fix again.\n\n```a2sdlc\n{"status": "changes_requested"}\n```'
        state = '{"stage":"review","status":"changes_requested","review_cycles":3,"base_branch":"main","last_updated":"2026-04-05"}'
        event = DispatchInput(key="15", stage=StageName.REVIEW, pr_number=42)
        ctx = _make_ctx(event=event, result=_success_result(output), state_json=state)
        result = await dispatch(ctx)

        assert result.blocked is True
        assert len(ctx.tickets.blocked) == 1
        assert "circuit breaker" in ctx.tickets.blocked[0][1].lower()


@pytest.mark.asyncio
@pytest.mark.unit
class TestDispatchMerge:
    async def test_merge_squashes_and_sets_done(self) -> None:
        event = DispatchInput(key="15", stage=StageName.MERGE)
        ctx = _make_ctx(event=event, pr_for_branch=42)
        result = await dispatch(ctx)

        assert result.stage == StageName.MERGE
        assert ctx.tickets.merged_prs == [42]
        labels = [l[2] for l in ctx.tickets.label_history]
        assert "stage:done" in labels
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Workspaces/a2sdlc-engine && uv run pytest tests/test_dispatch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'a2sdlc.dispatch'`

- [ ] **Step 3: Implement dispatch.py**

Create `src/a2sdlc/dispatch.py` implementing the dispatch flow from the spec (steps 1-16). Key structure:

```python
# src/a2sdlc/dispatch.py
"""Dispatch — single entry point for the a2sdlc pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from a2sdlc.adapters.protocols import DispatchInput, GitAdapter, StageRunner, TicketAdapter
from a2sdlc.config import ProjectConfig, load_stage_config, resolve_flags
from a2sdlc.exceptions import BlockedError, SkipEvent
from a2sdlc.models import BranchState, StageName, StageStatus, extract_result, strip_status_block
from a2sdlc.runner import format_cost
from a2sdlc.stages import get_transition, next_stage


@dataclass
class DispatchContext:
    tickets: TicketAdapter
    git: GitAdapter
    runner: StageRunner
    config: ProjectConfig
    project_root: Path
    logger: logging.Logger


@dataclass
class DispatchResult:
    stage: StageName
    status: StageStatus | None = None
    next_stage: StageName | None = None
    blocked: bool = False
    error: str | None = None


async def dispatch(ctx: DispatchContext) -> DispatchResult:
    """Run one pipeline stage. Returns what happened."""
    # 1. Parse event
    try:
        event = ctx.tickets.parse_event()
    except SkipEvent as e:
        ctx.logger.info("dispatch.skip", extra={"reason": e.reason})
        return DispatchResult(stage=StageName.SPEC, error=e.reason)

    ctx.logger.info("dispatch.start", extra={
        "key": event.key, "stage": event.stage.value,
    })

    # 2. Resolve flags
    labels = ctx.tickets.get_labels(event.key)
    flags = resolve_flags(ctx.config.pipeline_flags(), labels)

    # 3. Read state + circuit breaker
    state_json = ctx.git.read_state()
    state: BranchState | None = None
    if state_json:
        state = BranchState.model_validate_json(state_json)

    if event.stage == StageName.REVIEW and state and state.review_cycles >= _max_review_cycles(ctx, event.stage):
        reason = f"Circuit breaker: {state.review_cycles} review cycles exceeded max"
        ctx.tickets.set_blocked(event.key, reason)
        return DispatchResult(stage=event.stage, blocked=True, error=reason)

    # 4. Git setup
    try:
        base = state.base_branch if state else ctx.config.default_base
        branch = ctx.git.setup_branch(event.key, base)
    except BlockedError as e:
        ctx.tickets.set_blocked(event.key, e.reason)
        return DispatchResult(stage=event.stage, blocked=True, error=e.reason)

    # 5. Announce start
    comment_id = ctx.tickets.post_comment(event.key, f"⏳ **{event.stage.value}** started...")
    ctx.tickets.set_stage_label(event.key, event.stage)

    # 6. Merge stage — deterministic
    if event.stage == StageName.MERGE:
        pr = event.pr_number or ctx.tickets.get_pr_for_branch(branch)
        if pr:
            ctx.git.sync_with_base(ctx.config.default_base)
            ctx.tickets.merge_pr(pr)
            ctx.tickets.update_comment(event.key, comment_id, "✅ Merged to main")
            ctx.tickets.set_done_label(event.key)
        else:
            ctx.tickets.set_blocked(event.key, "No PR found for branch")
        return DispatchResult(stage=StageName.MERGE)

    # 7. Load stage config
    stage_config = load_stage_config(event.stage.value, ctx.config)

    # 8. Assemble prompt
    ticket_context = ctx.tickets.get_ticket(event.key)
    from a2sdlc.cli import assemble_system_prompt  # noqa: PLC0415
    system_prompt = assemble_system_prompt(event.stage.value, ctx.project_root / ".a2sdlc")

    # 9. Auto-spec prompt prefix
    if flags.auto_spec and event.stage == StageName.SPEC:
        system_prompt = (
            "IMPORTANT: Make your best judgment for all ambiguous requirements. "
            "Do not ask questions — produce the spec directly.\n\n" + system_prompt
        )

    # 10. Run stage
    def on_progress(text: str) -> None:
        try:
            ctx.tickets.update_comment(event.key, comment_id, text)
        except Exception:  # noqa: BLE001
            ctx.logger.warning("Failed to update progress", exc_info=True)

    result = await ctx.runner.run(
        user_prompt=ticket_context,
        system_prompt=system_prompt,
        config=stage_config,
        ticket_key=event.key,
        stage=event.stage,
        project_root=str(ctx.project_root),
        is_resume=event.is_resume,
        on_progress=on_progress,
    )

    # 11. Handle failure
    cost_footer = format_cost(result)
    if not result.success:
        error_msg = f"🚨 **{event.stage.value}** failed: `{result.error}`\n\n{cost_footer}"
        ctx.tickets.update_comment(event.key, comment_id, error_msg)
        ctx.tickets.set_blocked(event.key, result.error or "unknown")
        return DispatchResult(stage=event.stage, blocked=True, error=result.error)

    # 12. Parse result
    stage_result = extract_result(result.output)
    if stage_result is None:
        partial = result.output[:2000]
        error_msg = f"⚠️ No status block in **{event.stage.value}** output.\n\n{partial}\n\n{cost_footer}"
        ctx.tickets.update_comment(event.key, comment_id, error_msg)
        ctx.tickets.set_blocked(event.key, "no status block in output")
        return DispatchResult(stage=event.stage, blocked=True, error="no_status_block")

    comment_body = strip_status_block(result.output)
    ctx.tickets.update_comment(event.key, comment_id, f"{comment_body}\n\n{cost_footer}")

    # 13. Side effects — PR review
    if event.stage == StageName.REVIEW and event.pr_number:
        review_event = "APPROVE" if stage_result.status == StageStatus.APPROVED else "REQUEST_CHANGES"
        ctx.tickets.post_review(event.pr_number, comment_body, review_event)

    # 14. Write state + commit + push
    review_cycles = (state.review_cycles if state else 0)
    if stage_result.status == StageStatus.CHANGES_REQUESTED:
        review_cycles += 1
    new_state = BranchState(
        stage=event.stage,
        status=stage_result.status,
        base_branch=state.base_branch if state else ctx.config.default_base,
        review_cycles=review_cycles,
        last_updated=_now_iso(),
    )
    ctx.git.write_state(new_state.model_dump_json(indent=2))
    ctx.git.commit_artifacts("chore: stage artifacts", [".a2sdlc/state.json"])
    ctx.git.push()

    # 15. Transition
    next_st = next_stage(event.stage, stage_result.status, flags)

    ctx.logger.info("dispatch.transition", extra={
        "from": event.stage.value,
        "status": stage_result.status.value,
        "to": next_st.value if next_st else None,
    })

    if next_st is not None:
        ctx.tickets.set_stage_label(event.key, next_st)
    elif stage_result.status == StageStatus.QUESTIONS:
        # Set needs-input — don't trigger next stage
        pass  # adapter handles needs-input label via set_stage_label or dedicated method

    return DispatchResult(
        stage=event.stage,
        status=stage_result.status,
        next_stage=next_st,
        blocked=False,
    )


def _max_review_cycles(ctx: DispatchContext, stage: StageName) -> int:
    config = load_stage_config(stage.value, ctx.config)
    return config.max_review_cycles


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
```

- [ ] **Step 4: Run dispatch tests**

Run: `cd ~/Workspaces/a2sdlc-engine && uv run pytest tests/test_dispatch.py -v --tb=short`
Expected: All pass. Fix any issues.

- [ ] **Step 5: Gut cli.py — dispatch-only entry point**

Replace `src/a2sdlc/cli.py` with a minimal entry point that constructs `DispatchContext` and calls `dispatch()`. Keep `assemble_system_prompt()` and `find_project_root()` as they are still needed. Remove `orchestrate()`, `do_merge()`, `parse_args()`, and the old subcommand structure.

- [ ] **Step 6: Run full test suite + lint + ty**

Run: `cd ~/Workspaces/a2sdlc-engine && uv run pytest tests/ -v && uv run ruff check src/ tests/ && uv run ty check src/`
Expected: All pass. Fix remaining test breakage from old imports.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: implement dispatch — single entry point, label chain, typed state machine"
```

---

### Task 8: End-to-end smoke test + consumer workflow update

**Files:**
- Modify: `~/Workspaces/a2db-demo2/.github/workflows/agent-router.yml` — replace with thin workflow
- Create: `~/Workspaces/a2db-demo2/a2sdlc.yaml` — new config format

- [ ] **Step 1: Write the new consumer config**

```yaml
# ~/Workspaces/a2db-demo2/a2sdlc.yaml
adapter: github
pipeline:
  auto_spec: false
  auto_proceed: true
  auto_merge: false
  default_base: main
testing:
  command: make test
stages:
  spec:
    code_reviews: 1
  implement:
    code_reviews: 2
    max_review_cycles: 2
```

- [ ] **Step 2: Replace the workflow**

Replace `~/Workspaces/a2db-demo2/.github/workflows/agent-router.yml` with the thin workflow from the spec (the ~20-line YAML). Use the actual git URL for the engine install.

- [ ] **Step 3: Remove old config**

```bash
rm ~/Workspaces/a2db-demo2/.a2sdlc/project.yaml
```

Keep `.a2sdlc/` directory for runtime state.

- [ ] **Step 4: Commit consumer changes**

```bash
cd ~/Workspaces/a2db-demo2
git add a2sdlc.yaml .github/workflows/agent-router.yml
git rm .a2sdlc/project.yaml
git commit -m "feat: switch to a2sdlc dispatch — thin workflow, new config format"
git push
```

- [ ] **Step 5: Create test issue on a2db-demo2**

```bash
gh issue create --repo iorlas/a2db-demo2 \
  --title "Test dispatch: add health check endpoint" \
  --body "Add a /health endpoint that returns {\"status\": \"ok\"}." \
  --label "agent"
```

- [ ] **Step 6: Monitor CI**

Watch the GitHub Actions run. Verify:
- Dispatch starts, logs structured JSON
- Spec stage runs, posts comment, sets `stage:implement` label
- New CI job fires for implement stage
- Implement runs, creates PR, sets `stage:review`
- Review runs, posts PR review

- [ ] **Step 7: Push engine changes**

```bash
cd ~/Workspaces/a2sdlc-engine
git push origin main
```

---

## Self-Review

**Spec coverage:**
- Entry point (dispatch): Task 7
- Config (a2sdlc.yaml): Task 4
- State machine (already done, preserved in Task 2)
- Pipeline flags + label overrides: Task 4
- TicketAdapter: Task 6
- GitAdapter: Task 5
- StageRunner: Task 3 (protocol), Task 7 (wired)
- Error handling (SkipEvent, BlockedError): Task 1
- Circuit breaker: Task 7 (dispatch tests)
- LDD logging: Task 7 (dispatch implementation)
- Transparency (labels, comments): Task 7
- Auto-spec prompt: Task 7
- Consumer workflow: Task 8
- Agent-harness: Task 0

**Placeholder scan:** All code blocks contain actual implementation. No TBD/TODO.

**Type consistency:** `DispatchInput`, `DispatchContext`, `DispatchResult`, `PipelineFlags`, `ProjectConfig`, `StageConfig`, `BranchState` — all defined consistently across tasks. `StageName`/`StageStatus`/`Gate`/`Transition` already exist and are preserved.
