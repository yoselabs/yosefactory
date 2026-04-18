# Adapters Kind-First Layout — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure `src/a2sdlc/adapters/` from flat to kind-first subfolders, consolidate scattered `Protocol` definitions, move `PipelineEvent` to `domain/`, and mirror the new layout in `tests/adapters/`. Zero behavior change — all existing tests must continue passing.

**Architecture:** Four atomic commits, each leaving `make check` green. Commit 1 extracts kinds (`git/`, `work/`, `review/`, `subscriber/`, `runner/`) and consolidates Protocols into each kind's `__init__.py`. Commit 2 splits the fat `github.py` into `work/github.py` + `review/github.py` + `_github.py`. Commit 3 moves `PipelineEvent` to `domain/`. Commit 4 mirrors the layout in tests.

**Tech Stack:** Python 3.12, `uv`, `pytest`, `ty` (type checker), `import-linter` (architecture contracts), `ruff` (format/lint), `agent-harness` (quality gate).

**Spec reference:** `docs/superpowers/specs/2026-04-19-adapters-kind-first-layout-design.md`

**Branch context:** Plan assumes `main` has the merged `feat/local-runner` branch. Execute on a fresh branch `feat/adapters-layout` off `main`.

**Risk profile:** Pure refactor, no new tests. Failure mode is import errors or stale string references (`patch("...")`, `logger=...`) caught only at test-run time. Each task ends with `make check` to catch those early.

---

## Task 0: Baseline and branch setup

**Files:** None modified. Records starting state.

- [ ] **Step 1: Verify clean working tree on main with feat/local-runner merged**

```bash
git status
git log --oneline -3
```

Expected: working tree clean; HEAD shows the merged observability commits from `feat/local-runner`.

If `feat/local-runner` is not yet merged into `main`: abort this plan. The spec explicitly targets a fresh branch off merged `main`.

- [ ] **Step 2: Create and check out the implementation branch**

```bash
git checkout -b feat/adapters-layout
```

- [ ] **Step 3: Run baseline test count and record it**

```bash
uv run pytest --tb=no -q 2>&1 | tail -3
```

Expected: `NNN passed` where NNN is the current count. Record this number (e.g. "527"). After Commit 4 the count must match exactly — any difference means a test was accidentally deleted or skipped during a move.

- [ ] **Step 4: Run `make check` to confirm green starting state**

```bash
make check
```

Expected: all checks pass.

---

## Task 1.1: Extract `runner/` kind (Protocol only)

**Files:**
- Create: `src/a2sdlc/adapters/runner/__init__.py`
- Modify: `src/a2sdlc/adapters/protocols.py` (remove `StageRunner`)
- Modify: `src/a2sdlc/adapters/__init__.py` (update re-export source)
- Modify: `src/a2sdlc/cli_local.py:37` (TYPE_CHECKING import path)
- Modify: `src/a2sdlc/pipeline/dispatch.py:10` (import path)
- Modify: `src/a2sdlc/pipeline/stage_executor.py:8` (import path)

**Rationale:** `runner/` is the simplest kind — Protocol only, no impls in tree (SdkStageRunner lives in `pipeline/runner.py`). Doing it first establishes the pattern and shrinks `protocols.py` by one class.

- [ ] **Step 1: Create `src/a2sdlc/adapters/runner/__init__.py`**

```python
"""StageRunner Protocol — contract for AI-stage execution adapters.

No in-tree impls: ``SdkStageRunner`` lives in ``pipeline/runner.py`` (it composes the
Claude Agent SDK and belongs to the pipeline layer, not adapters). This subfolder
exists solely to hold the Protocol and give the adapters/ layout kind-first
uniformity; future runner variants (fake, retrying, recording) would land here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from a2sdlc.config import StageConfig
from a2sdlc.domain.models import StageName
from a2sdlc.domain.run_result import RunResult

if TYPE_CHECKING:
    from a2sdlc.evaluation.progress import ProgressState


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
        progress_state: "ProgressState",
        is_resume: bool = False,
        branch: str = "",
    ) -> RunResult: ...


__all__ = ["StageRunner"]
```

- [ ] **Step 2: Remove `StageRunner` from `src/a2sdlc/adapters/protocols.py`**

Edit the file to remove the `StageRunner` class (lines 26-40 in current file) and its associated `ProgressState` TYPE_CHECKING import if no other class needs it. After editing, `protocols.py` should contain only `GitAdapter` and `Subscriber` plus the TYPE_CHECKING block for `ProgressState` (used by `Subscriber`).

- [ ] **Step 3: Update `src/a2sdlc/adapters/__init__.py` re-export source for `StageRunner`**

Change:
```python
from a2sdlc.adapters.protocols import (
    GitAdapter,
    StageRunner,
)
```
to:
```python
from a2sdlc.adapters.protocols import GitAdapter
from a2sdlc.adapters.runner import StageRunner
```

Keep `__all__` unchanged.

- [ ] **Step 4: Update `src/a2sdlc/cli_local.py` TYPE_CHECKING import**

Replace:
```python
    from a2sdlc.adapters.protocols import StageRunner
```
with:
```python
    from a2sdlc.adapters.runner import StageRunner
```

- [ ] **Step 5: Update `src/a2sdlc/pipeline/dispatch.py` import**

Replace:
```python
from a2sdlc.adapters.protocols import GitAdapter, StageRunner
```
with:
```python
from a2sdlc.adapters.protocols import GitAdapter
from a2sdlc.adapters.runner import StageRunner
```

- [ ] **Step 6: Update `src/a2sdlc/pipeline/stage_executor.py` import**

Replace:
```python
from a2sdlc.adapters.protocols import StageRunner
```
with:
```python
from a2sdlc.adapters.runner import StageRunner
```

- [ ] **Step 7: Run `make check`**

```bash
make check
```

Expected: all checks pass. `StageRunner` is a structural Protocol with no direct runtime test — `ty`'s Protocol conformance checking is what verifies the new `runner/__init__.py` definition matches how dispatch and stage_executor use it. If `ty` fails, a StageRunner import was missed or the Protocol signature drifted. If tests fail, a string-form reference slipped through (shouldn't happen for runner since no test patches touch it).

---

## Task 1.2: Extract `subscriber/` kind

**Files:**
- Create: `src/a2sdlc/adapters/subscriber/__init__.py`
- Create (via `git mv`): `src/a2sdlc/adapters/subscriber/console.py`, `gh_actions.py`, `gh_comment.py`, `mlflow_trace.py`
- Modify: `src/a2sdlc/adapters/protocols.py` (remove `Subscriber`)
- Modify: `src/a2sdlc/adapters/__init__.py` (update source)
- Modify: `src/a2sdlc/evaluation/progress.py:13` (TYPE_CHECKING import)
- Modify: `src/a2sdlc/cli.py:132` (subscriber import)
- Modify: `src/a2sdlc/cli_local.py:177,181,190` (subscriber imports)
- Modify: `src/a2sdlc/pipeline/dispatch.py:203` (subscriber import)
- Modify: `tests/adapters/test_mlflow_trace_subscriber.py:68` (patch string)
- Modify: `tests/adapters/test_console_subscriber.py:7`, `test_gh_actions_subscriber.py:7`, `test_gh_comment_subscriber.py:7`, `test_mlflow_trace_subscriber.py:9` (module imports)
- Modify: `pyproject.toml` (import-linter `ignore_imports`)

- [ ] **Step 1: Create `src/a2sdlc/adapters/subscriber/__init__.py` with the `Subscriber` Protocol and re-exports**

```python
"""Subscriber Protocol + in-tree subscriber impls.

Subscribers consume ``ProgressEvent`` instances from ``ProgressState``. Concrete
impls filter events by ``isinstance`` and ignore types they don't handle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from a2sdlc.evaluation.progress import ProgressEvent


class Subscriber(Protocol):
    """Receives ``ProgressEvent`` instances from ``ProgressState``.

    Implementations filter by ``isinstance`` and ignore event types they
    don't care about. ``handle`` is async because the runner is already
    async; sync subscribers just don't ``await`` anything inside.
    """

    async def handle(self, event: "ProgressEvent") -> None: ...


from a2sdlc.adapters.subscriber.console import ConsoleSubscriber  # noqa: E402
from a2sdlc.adapters.subscriber.gh_actions import GhActionsLogSubscriber  # noqa: E402
from a2sdlc.adapters.subscriber.gh_comment import GhCommentSubscriber  # noqa: E402
from a2sdlc.adapters.subscriber.mlflow_trace import MlflowTraceSubscriber  # noqa: E402

__all__ = [
    "Subscriber",
    "ConsoleSubscriber",
    "GhActionsLogSubscriber",
    "GhCommentSubscriber",
    "MlflowTraceSubscriber",
]
```

- [ ] **Step 2: Move subscriber files into `subscriber/` with rename**

```bash
git mv src/a2sdlc/adapters/console_subscriber.py src/a2sdlc/adapters/subscriber/console.py
git mv src/a2sdlc/adapters/gh_actions_subscriber.py src/a2sdlc/adapters/subscriber/gh_actions.py
git mv src/a2sdlc/adapters/gh_comment_subscriber.py src/a2sdlc/adapters/subscriber/gh_comment.py
git mv src/a2sdlc/adapters/mlflow_trace_subscriber.py src/a2sdlc/adapters/subscriber/mlflow_trace.py
```

- [ ] **Step 3: Remove `Subscriber` class from `src/a2sdlc/adapters/protocols.py`**

After this edit, `protocols.py` should contain only the `GitAdapter` class. Drop the `if TYPE_CHECKING: from a2sdlc.evaluation.progress import ProgressEvent, ProgressState` block since only `Subscriber` used it.

- [ ] **Step 4: Update `src/a2sdlc/adapters/__init__.py`**

Change imports block. After this step:
```python
"""Adapter registry."""

from __future__ import annotations

from a2sdlc.adapters.protocols import GitAdapter
from a2sdlc.adapters.review import Approval, ReviewAdapter, ReviewComment
from a2sdlc.adapters.runner import StageRunner
from a2sdlc.adapters.work import PipelineEvent, WorkAdapter

__all__ = [
    "GitAdapter",
    "StageRunner",
    "PipelineEvent",
    "WorkAdapter",
    "Approval",
    "ReviewComment",
    "ReviewAdapter",
]
```

- [ ] **Step 5: Update `src/a2sdlc/evaluation/progress.py:13` TYPE_CHECKING import**

Replace:
```python
    from a2sdlc.adapters.protocols import Subscriber
```
with:
```python
    from a2sdlc.adapters.subscriber import Subscriber
```

- [ ] **Step 6: Update `src/a2sdlc/cli.py` subscriber import**

Replace:
```python
        from a2sdlc.adapters.gh_actions_subscriber import GhActionsLogSubscriber  # noqa: PLC0415
```
with:
```python
        from a2sdlc.adapters.subscriber.gh_actions import GhActionsLogSubscriber  # noqa: PLC0415
```

- [ ] **Step 7: Update `src/a2sdlc/cli_local.py` subscriber imports (3 sites)**

Replace:
```python
        from a2sdlc.adapters.gh_actions_subscriber import GhActionsLogSubscriber  # noqa: PLC0415
```
with:
```python
        from a2sdlc.adapters.subscriber.gh_actions import GhActionsLogSubscriber  # noqa: PLC0415
```

Replace:
```python
        from a2sdlc.adapters.console_subscriber import ConsoleSubscriber  # noqa: PLC0415
```
with:
```python
        from a2sdlc.adapters.subscriber.console import ConsoleSubscriber  # noqa: PLC0415
```

Replace:
```python
        from a2sdlc.adapters.mlflow_trace_subscriber import (  # noqa: PLC0415
            MlflowTraceSubscriber,
        )
```
with:
```python
        from a2sdlc.adapters.subscriber.mlflow_trace import (  # noqa: PLC0415
            MlflowTraceSubscriber,
        )
```

- [ ] **Step 8: Update `src/a2sdlc/pipeline/dispatch.py:203` subscriber import**

Replace:
```python
    from a2sdlc.adapters.gh_comment_subscriber import GhCommentSubscriber  # noqa: PLC0415
```
with:
```python
    from a2sdlc.adapters.subscriber.gh_comment import GhCommentSubscriber  # noqa: PLC0415
```

- [ ] **Step 9: Update test imports**

Replace in each file:

`tests/adapters/test_console_subscriber.py:7`:
```python
from a2sdlc.adapters.console_subscriber import ConsoleSubscriber
```
→
```python
from a2sdlc.adapters.subscriber.console import ConsoleSubscriber
```

`tests/adapters/test_gh_actions_subscriber.py:7`:
```python
from a2sdlc.adapters.gh_actions_subscriber import GhActionsLogSubscriber
```
→
```python
from a2sdlc.adapters.subscriber.gh_actions import GhActionsLogSubscriber
```

`tests/adapters/test_gh_comment_subscriber.py:7`:
```python
from a2sdlc.adapters.gh_comment_subscriber import GhCommentSubscriber
```
→
```python
from a2sdlc.adapters.subscriber.gh_comment import GhCommentSubscriber
```

`tests/adapters/test_mlflow_trace_subscriber.py:9`:
```python
from a2sdlc.adapters.mlflow_trace_subscriber import MlflowTraceSubscriber
```
→
```python
from a2sdlc.adapters.subscriber.mlflow_trace import MlflowTraceSubscriber
```

- [ ] **Step 10: Update `patch()` string in `tests/adapters/test_mlflow_trace_subscriber.py:68`**

Replace:
```python
    monkeypatch.setattr(
        "a2sdlc.adapters.mlflow_trace_subscriber.mlflow.start_span_no_context",
        fake.start_span_no_context,
    )
```
with:
```python
    monkeypatch.setattr(
        "a2sdlc.adapters.subscriber.mlflow_trace.mlflow.start_span_no_context",
        fake.start_span_no_context,
    )
```

- [ ] **Step 11: Update `pyproject.toml` `ignore_imports` for subscriber modules**

Change in the "adapters do not import application layer" contract block (around lines 84-98):

Replace:
```toml
    "a2sdlc.adapters.console_subscriber -> a2sdlc.evaluation.progress",
    "a2sdlc.adapters.gh_actions_subscriber -> a2sdlc.evaluation.progress",
    "a2sdlc.adapters.gh_comment_subscriber -> a2sdlc.evaluation.progress",
    "a2sdlc.adapters.gh_comment_subscriber -> a2sdlc.evaluation.throttle",
    "a2sdlc.adapters.mlflow_trace_subscriber -> a2sdlc.evaluation.progress",
```
with:
```toml
    "a2sdlc.adapters.subscriber.console -> a2sdlc.evaluation.progress",
    "a2sdlc.adapters.subscriber.gh_actions -> a2sdlc.evaluation.progress",
    "a2sdlc.adapters.subscriber.gh_comment -> a2sdlc.evaluation.progress",
    "a2sdlc.adapters.subscriber.gh_comment -> a2sdlc.evaluation.throttle",
    "a2sdlc.adapters.subscriber.mlflow_trace -> a2sdlc.evaluation.progress",
```

Also update the `a2sdlc.adapters.protocols -> a2sdlc.evaluation.progress` entry in this SAME contract — change it to `a2sdlc.adapters.subscriber -> a2sdlc.evaluation.progress`.

In the second contract "lifecycle does not import assembly or evaluation" (around lines 113-124), update the ignore_imports entry:
Replace:
```toml
    "a2sdlc.adapters.protocols -> a2sdlc.evaluation.progress",
```
with:
```toml
    "a2sdlc.adapters.subscriber -> a2sdlc.evaluation.progress",
```

- [ ] **Step 12: Run `make check`**

```bash
make check
```

Expected: all checks pass. If `lint-imports` fails, an `ignore_imports` entry is wrong. If a patch fails at test time, a string wasn't updated.

---

## Task 1.3: Extract `git/` kind

**Files:**
- Create: `src/a2sdlc/adapters/git/__init__.py`
- Create (via `git mv`): `src/a2sdlc/adapters/git/local.py`, `git/local_branch.py`
- Modify: `src/a2sdlc/adapters/protocols.py` (remove `GitAdapter` — this empties the file)
- Delete: `src/a2sdlc/adapters/protocols.py`
- Modify: `src/a2sdlc/adapters/__init__.py` (update re-export source for `GitAdapter`)
- Modify: `src/a2sdlc/adapters/git/local_branch.py` (internal import path, if needed)
- Modify: `src/a2sdlc/adapters/factory.py` (2 LocalGitAdapter/LocalBranchGitAdapter imports)
- Modify: `src/a2sdlc/cli.py:133` (LocalGitAdapter import)
- Modify: `src/a2sdlc/lifecycle/state.py:7` (GitAdapter import)
- Modify: `tests/adapters/test_git.py` (11 patch strings + module import)
- Modify: `tests/adapters/test_local_branch_git.py` (imports)
- Modify: `tests/adapters/test_factory.py` (LocalBranchGitAdapter import)
- Modify: `tests/test_cli.py:214` (patch string)

- [ ] **Step 1: Create `src/a2sdlc/adapters/git/__init__.py`**

```python
"""GitAdapter Protocol + in-tree git impls."""

from __future__ import annotations

from typing import Protocol


class GitAdapter(Protocol):
    """Local git operations."""

    def setup_branch(self, branch_name: str, base: str) -> str: ...
    def sync_with_base(self, base: str) -> bool: ...
    def commit_artifacts(self, message: str, paths: list[str]) -> bool: ...
    def push(self) -> None: ...
    def read_state(self) -> str | None: ...
    def write_state(self, data: str) -> None: ...


from a2sdlc.adapters.git.local import LocalGitAdapter  # noqa: E402
from a2sdlc.adapters.git.local_branch import LocalBranchGitAdapter  # noqa: E402

__all__ = ["GitAdapter", "LocalGitAdapter", "LocalBranchGitAdapter"]
```

- [ ] **Step 2: Move `git.py` → `git/local.py`**

```bash
git mv src/a2sdlc/adapters/git.py src/a2sdlc/adapters/git/local.py
```

- [ ] **Step 3: Move `local_branch_git.py` → `git/local_branch.py`**

```bash
git mv src/a2sdlc/adapters/local_branch_git.py src/a2sdlc/adapters/git/local_branch.py
```

- [ ] **Step 4: Fix `local_branch.py`'s internal import**

The file previously had `from a2sdlc.adapters.git import LocalGitAdapter`. That still resolves (git/ is now the package and `__init__.py` re-exports it) — but it creates a circular reference during package initialization (git/__init__.py imports local_branch which imports from git which triggers __init__.py). Change it to a direct submodule import.

Replace in `src/a2sdlc/adapters/git/local_branch.py`:
```python
from a2sdlc.adapters.git import LocalGitAdapter
```
with:
```python
from a2sdlc.adapters.git.local import LocalGitAdapter
```

- [ ] **Step 5: Delete `src/a2sdlc/adapters/protocols.py`**

After Tasks 1.1 and 1.2, `protocols.py` contains only `GitAdapter`. Since `git/__init__.py` now defines `GitAdapter`, the old file is redundant. Delete it:

```bash
git rm src/a2sdlc/adapters/protocols.py
```

- [ ] **Step 6: Update `src/a2sdlc/adapters/__init__.py` `GitAdapter` source**

Replace:
```python
from a2sdlc.adapters.protocols import GitAdapter
```
with:
```python
from a2sdlc.adapters.git import GitAdapter
```

After this step, the file should look like:
```python
"""Adapter registry."""

from __future__ import annotations

from a2sdlc.adapters.git import GitAdapter
from a2sdlc.adapters.review import Approval, ReviewAdapter, ReviewComment
from a2sdlc.adapters.runner import StageRunner
from a2sdlc.adapters.work import PipelineEvent, WorkAdapter

__all__ = [
    "GitAdapter",
    "StageRunner",
    "PipelineEvent",
    "WorkAdapter",
    "Approval",
    "ReviewComment",
    "ReviewAdapter",
]
```

- [ ] **Step 7: Update `src/a2sdlc/adapters/factory.py`**

Replace:
```python
from a2sdlc.adapters.local_branch_git import LocalBranchGitAdapter
```
with:
```python
from a2sdlc.adapters.git import LocalBranchGitAdapter
```

Also replace the lazy import:
```python
        from a2sdlc.adapters.git import LocalGitAdapter  # noqa: PLC0415
```
stays the same — `git/__init__.py` re-exports it.

- [ ] **Step 8: Update `src/a2sdlc/cli.py:133`**

Replace:
```python
        from a2sdlc.adapters.git import LocalGitAdapter  # noqa: PLC0415
```
This import already works via re-export. No change needed — but verify by `make check`.

- [ ] **Step 9: Update `src/a2sdlc/lifecycle/state.py:7`**

Replace:
```python
from a2sdlc.adapters.protocols import GitAdapter
```
with:
```python
from a2sdlc.adapters.git import GitAdapter
```

- [ ] **Step 10: Update `tests/adapters/test_git.py` `patch()` strings (11 sites)**

Every occurrence of `patch("a2sdlc.adapters.git.Repo")` becomes `patch("a2sdlc.adapters.git.local.Repo")`. Do a global replace in that file:

```bash
# Verify the count first
grep -c 'patch("a2sdlc\.adapters\.git\.Repo")' tests/adapters/test_git.py
# Should print: 11
```

Then replace all 11 strings in-place:
```python
# In tests/adapters/test_git.py, every line like:
#     with patch("a2sdlc.adapters.git.Repo") as MockRepo:
# becomes:
#     with patch("a2sdlc.adapters.git.local.Repo") as MockRepo:
```

Also update the module import at the top if any (`from a2sdlc.adapters.git import LocalGitAdapter` stays — re-export handles it).

- [ ] **Step 11: Update `tests/adapters/test_local_branch_git.py`**

Replace:
```python
from a2sdlc.adapters.local_branch_git import LocalBranchGitAdapter
```
with:
```python
from a2sdlc.adapters.git import LocalBranchGitAdapter
```

- [ ] **Step 12: Update `tests/adapters/test_factory.py`**

Replace:
```python
from a2sdlc.adapters.local_branch_git import LocalBranchGitAdapter
```
with:
```python
from a2sdlc.adapters.git import LocalBranchGitAdapter
```

- [ ] **Step 13: Update `tests/test_cli.py:214`**

Replace:
```python
            patch("a2sdlc.adapters.git.LocalGitAdapter") as mock_git,
```
with:
```python
            patch("a2sdlc.adapters.git.local.LocalGitAdapter") as mock_git,
```

- [ ] **Step 14: Run `make check`**

```bash
make check
```

Expected: all checks pass. If a `patch()` fails at test-run time with `AttributeError: <module> has no attribute 'Repo'`, a string was missed.

---

## Task 1.4: Convert `work.py` → `work/` package

**Files:**
- Create: `src/a2sdlc/adapters/work/__init__.py` (holds `PipelineEvent` + `WorkAdapter` Protocol)
- Create (via `git mv`): `src/a2sdlc/adapters/work/local_file.py`
- Delete: `src/a2sdlc/adapters/work.py` (its content moves to `work/__init__.py`)
- Modify: `src/a2sdlc/adapters/work/local_file.py:18` (import path)
- Modify: `src/a2sdlc/adapters/factory.py` (LocalFileWorkAdapter import)
- Modify: `tests/adapters/test_local_file_work.py` (import + 3 logger strings)
- Modify: `src/a2sdlc/adapters/local_noop_review.py` (no change needed — imports from `a2sdlc.adapters.review` which stays a flat module after this task)

**Ordering hazard reminder:** `adapters/github.py` currently imports `from a2sdlc.adapters.work import PipelineEvent`. That import must keep resolving. Since we create `work/` as a package with `PipelineEvent` in its `__init__.py` *before* deleting the flat `work.py`, resolution transitions smoothly. Do **not** edit `adapters/github.py`'s imports in this task.

**Step ordering note:** steps below are ordered so that each intermediate disk state is coherent — if you run `make check` between any two steps (some executors do), it stays green. The trick: move the impl file into the new `work/` folder *first* (this atomically creates the folder and shadows the old flat `work.py`), then create the `__init__.py`, then delete the old flat `work.py`.

- [ ] **Step 1: Move `local_file_work.py` → `work/local_file.py` (atomically creates `work/` directory)**

```bash
git mv src/a2sdlc/adapters/local_file_work.py src/a2sdlc/adapters/work/local_file.py
```

`git mv A B/C` where `B/` doesn't exist creates `B/` atomically — there's no transient state where both `work.py` (file) and `work/` (dir) sit as sibling flat+package names.

- [ ] **Step 2: Create `src/a2sdlc/adapters/work/__init__.py`**

Copy the full content of current `src/a2sdlc/adapters/work.py`, then append the local_file re-export:

```python
"""WorkAdapter Protocol + PipelineEvent + in-tree work impls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from a2sdlc.domain.handover import FeedbackItem, HandoverComment
from a2sdlc.domain.models import StageName


@dataclass
class PipelineEvent:
    """Normalized pipeline event from a work adapter.

    trigger_stage: what the event literally says (label value, or None for feedback/proceed).
    is_feedback: True for comment/review events, False for label events.
    The engine resolves the actual target stage via the routing table.
    """

    key: str
    trigger_stage: StageName | None = None
    is_feedback: bool = False
    pr_number: int | None = None


class WorkAdapter(Protocol):
    """Platform-specific ticket/work-item operations."""

    def parse_event(self) -> PipelineEvent: ...
    def get_ticket(self, key: str) -> str: ...
    def get_labels(self, key: str) -> list[str]: ...
    def begin_comment(self, key: str) -> str: ...
    def update_progress(self, comment_id: str, body: str) -> None: ...
    def finalize_comment(self, comment_id: str, body: str) -> None: ...
    def set_stage_label(self, key: str, stage: StageName) -> None: ...
    def set_done_label(self, key: str) -> None: ...
    def set_blocked(self, key: str, reason: str) -> None: ...
    def format_branch(self, ticket_key: str) -> str: ...
    def collect_issue_feedback(
        self, key: str, since: datetime
    ) -> list[FeedbackItem]: ...
    def find_last_handover(self, key: str) -> HandoverComment | None: ...


from a2sdlc.adapters.work.local_file import LocalFileWorkAdapter  # noqa: E402

__all__ = ["PipelineEvent", "WorkAdapter", "LocalFileWorkAdapter"]
```

- [ ] **Step 3: Delete the old flat `work.py`**

```bash
git rm src/a2sdlc/adapters/work.py
```

(`work/__init__.py` is now present and re-exports `PipelineEvent`/`WorkAdapter`, so any `from a2sdlc.adapters.work import …` imports resolve through the package.)

- [ ] **Step 4: Verify the internal import in `work/local_file.py` (no change needed)**

The file previously had `from a2sdlc.adapters.work import PipelineEvent`. That import stays — it now resolves through the new package. Since `PipelineEvent` lives in `work/__init__.py` (there's no `work/event.py`), the import must come from the package, not a submodule. Do NOT change this import yet — it stays as-is:

```python
from a2sdlc.adapters.work import PipelineEvent
```

But this creates a circular chain: `work/__init__.py` imports `work.local_file` which imports from `work` (the package). Python handles this because `PipelineEvent` is defined *before* the `from ... import LocalFileWorkAdapter` line in `work/__init__.py`. Verify by running `make check`.

If the circular import fails: split `PipelineEvent` out to `work/event.py` as an internal submodule, import from there in `work/local_file.py`, and have `work/__init__.py` re-export from `work.event`. (This is a contingency; the initial approach should work.)

- [ ] **Step 5: Update `factory.py` LocalFileWorkAdapter import**

Replace:
```python
from a2sdlc.adapters.local_file_work import LocalFileWorkAdapter
```
with:
```python
from a2sdlc.adapters.work import LocalFileWorkAdapter
```

- [ ] **Step 6: Update `tests/adapters/test_local_file_work.py` module import**

Replace:
```python
from a2sdlc.adapters.local_file_work import LocalFileWorkAdapter
```
with:
```python
from a2sdlc.adapters.work.local_file import LocalFileWorkAdapter
```

- [ ] **Step 7: Update `tests/adapters/test_local_file_work.py` logger strings (3 sites)**

All three `caplog.at_level(logging.INFO, logger="a2sdlc.adapters.local_file_work")` calls must become:
```python
    with caplog.at_level(logging.INFO, logger="a2sdlc.adapters.work.local_file"):
```

Verify count first:
```bash
grep -c 'logger="a2sdlc\.adapters\.local_file_work"' tests/adapters/test_local_file_work.py
# Should print: 3
```

Then replace all three. (If `local_file.py` uses `logger = logging.getLogger(__name__)`, the logger name automatically updated when the file moved.)

- [ ] **Step 8: Run `make check`**

```bash
make check
```

Expected: all checks pass. `github.py` still imports `from a2sdlc.adapters.work import PipelineEvent` — that must resolve through the new package.

---

## Task 1.5: Convert `review.py` → `review/` package

**Files:**
- Create: `src/a2sdlc/adapters/review/__init__.py` (holds `Approval`, `ReviewComment`, `ReviewAdapter` Protocol)
- Create (via `git mv`): `src/a2sdlc/adapters/review/local_noop.py`
- Delete: `src/a2sdlc/adapters/review.py` (content moves to `review/__init__.py`)
- Modify: `src/a2sdlc/adapters/review/local_noop.py` (logger string + imports)
- Modify: `src/a2sdlc/adapters/factory.py` (LocalNoopReviewAdapter import)
- Modify: `src/a2sdlc/cli_local.py:29` (LocalNoopReviewAdapter import)
- Modify: `tests/adapters/test_local_noop_review.py` (imports)

- [ ] **Step 1: Create `src/a2sdlc/adapters/review/__init__.py`**

```python
"""ReviewAdapter Protocol + Approval/ReviewComment data + in-tree review impls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from a2sdlc.domain.handover import FeedbackItem, HandoverComment


@dataclass(frozen=True)
class Approval:
    """A PR approval record."""

    user: str
    is_bot: bool


@dataclass(frozen=True)
class ReviewComment:
    """A PR review comment."""

    author: str
    body: str
    created_at: str


class ReviewAdapter(Protocol):
    """Platform-specific pull-request operations."""

    def create_draft_pr(
        self, branch: str, base: str, title: str, ticket_key: str
    ) -> int: ...
    def update_pr(
        self, pr_number: int, title: str, body: str, ticket_key: str
    ) -> None: ...
    def mark_pr_ready(self, pr_number: int) -> None: ...
    def merge_pr(self, pr_number: int, method: str = "squash") -> None: ...
    def get_approvals(self, pr_number: int) -> list[Approval]: ...
    def post_review(self, pr_number: int, body: str, verdict: str) -> None: ...
    def read_pr_diff(self, pr_number: int) -> str: ...
    def read_pr_comments(self, pr_number: int) -> list[ReviewComment]: ...
    def collect_pr_feedback(
        self, pr_number: int, since: datetime
    ) -> list[FeedbackItem]: ...
    def find_last_handover(self, pr_number: int) -> HandoverComment | None: ...


from a2sdlc.adapters.review.local_noop import LocalNoopReviewAdapter  # noqa: E402

__all__ = ["Approval", "ReviewComment", "ReviewAdapter", "LocalNoopReviewAdapter"]
```

- [ ] **Step 2: Delete flat `review.py`**

```bash
git rm src/a2sdlc/adapters/review.py
```

- [ ] **Step 3: Move `local_noop_review.py` → `review/local_noop.py`**

```bash
git mv src/a2sdlc/adapters/local_noop_review.py src/a2sdlc/adapters/review/local_noop.py
```

- [ ] **Step 4: Update the hardcoded logger in `review/local_noop.py`**

Replace:
```python
logger = logging.getLogger("a2sdlc.adapters.local_noop_review")
```
with:
```python
logger = logging.getLogger(__name__)
```

(Using `__name__` means the logger name tracks the module path automatically — `"a2sdlc.adapters.review.local_noop"` — and survives future renames.)

- [ ] **Step 5: Update `factory.py` LocalNoopReviewAdapter import**

Replace:
```python
from a2sdlc.adapters.local_noop_review import LocalNoopReviewAdapter
```
with:
```python
from a2sdlc.adapters.review import LocalNoopReviewAdapter
```

- [ ] **Step 6: Update `src/a2sdlc/cli_local.py:29`**

Replace:
```python
from a2sdlc.adapters.local_noop_review import LocalNoopReviewAdapter
```
with:
```python
from a2sdlc.adapters.review import LocalNoopReviewAdapter
```

- [ ] **Step 7: Update `tests/adapters/test_local_noop_review.py`**

Replace:
```python
from a2sdlc.adapters.local_noop_review import LocalNoopReviewAdapter
```
with:
```python
from a2sdlc.adapters.review.local_noop import LocalNoopReviewAdapter
```

- [ ] **Step 8: Run `make check`**

```bash
make check
```

Expected: all checks pass. `github.py` still imports `from a2sdlc.adapters.review import Approval, ReviewComment` — resolves through new package.

---

## Task 1.6: Run full gate and commit Commit 1

- [ ] **Step 1: Run import-linter explicitly**

```bash
uv run lint-imports
```

Expected: all contracts pass. If any fail, an `ignore_imports` entry is pointing at a dead module — check `pyproject.toml`.

- [ ] **Step 2: Run the full quality gate**

```bash
make check
```

Expected: all green.

- [ ] **Step 3: Verify no stale `adapters.protocols` references remain**

```bash
rg -n 'a2sdlc\.adapters\.protocols' src tests
```

Expected: zero matches (outside git history).

- [ ] **Step 4: Commit Commit 1**

```bash
git add -A
git commit -m "$(cat <<'EOF'
refactor(adapters): kind-first subfolder layout; consolidate Protocols

Reorganize adapters/ from flat 14-file folder into kind-first
subfolders. Each kind (git/, work/, review/, subscriber/, runner/) now
has its Protocol definition in __init__.py alongside re-exports of its
in-tree impls.

- git/ contains GitAdapter + LocalGitAdapter + LocalBranchGitAdapter
- work/ contains WorkAdapter + PipelineEvent + LocalFileWorkAdapter
- review/ contains ReviewAdapter + Approval + ReviewComment + LocalNoopReviewAdapter
- subscriber/ contains Subscriber + 4 concrete subscribers
- runner/ contains StageRunner Protocol only (SdkStageRunner stays in pipeline/)

Deletes the old protocols.py (content redistributed), work.py, and
review.py. github.py is NOT yet split — its imports from
a2sdlc.adapters.review and a2sdlc.adapters.work resolve through the new
packages until the next commit.

Updates import-linter ignore_imports in both contracts where the old
protocols module was referenced.

Updates all 11 patch("a2sdlc.adapters.git.Repo") strings in
test_git.py, the one patch string in test_mlflow_trace_subscriber.py,
and 3 logger= strings in test_local_file_work.py to match new paths.
Switches local_noop.py's hardcoded getLogger to __name__ so it tracks
future renames.

Zero behavior change. All tests still pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Verify commit message and test count**

```bash
git log --oneline -1
uv run pytest --tb=no -q 2>&1 | tail -3
```

Expected: test count unchanged from baseline recorded in Task 0.

---

## Task 2.1: Create `_github.py` shared helper

**Files:**
- Create: `src/a2sdlc/adapters/_github.py`

`_github.py` holds the `connect()` helper. Named with leading underscore to signal "private, not part of the public adapters surface." Constants like `STAGE_LABELS`, `TRIGGER_LABEL`, etc. are used only by `GitHubWorkAdapter`, so they move with it in Task 2.2 — not here.

- [ ] **Step 1: Create `src/a2sdlc/adapters/_github.py`**

```python
"""Shared PyGithub helpers for work/github.py and review/github.py.

Leading-underscore module name signals internal to the adapters package — not
re-exported at the adapters top level. Public entry is via ``connect(repo_name, token)``
called from ``cli.py`` to build a single ``Repository`` handle, which is then passed
to both ``GitHubWorkAdapter`` and ``GitHubReviewAdapter`` constructors.
"""

from __future__ import annotations

from github import Github
from github.Repository import Repository


def connect(repo_name: str, token: str) -> Repository:
    """Create a shared PyGithub repo handle. Pass to both adapters."""
    return Github(token).get_repo(repo_name)


__all__ = ["connect"]
```

- [ ] **Step 2: Verify the helper is importable**

```bash
uv run python -c "from a2sdlc.adapters._github import connect; print(connect)"
```

Expected: prints the function's repr. No `make check` yet — `cli.py` still uses the old `from a2sdlc.adapters.github import connect` which works because `github.py` still exists.

---

## Task 2.2: Carve out `work/github.py`

**Files:**
- Create: `src/a2sdlc/adapters/work/github.py` (GitHubWorkAdapter + label constants)
- Modify: `src/a2sdlc/adapters/work/__init__.py` (re-export GitHubWorkAdapter)

- [ ] **Step 1: Create `src/a2sdlc/adapters/work/github.py`**

Copy the GitHubWorkAdapter class from `src/a2sdlc/adapters/github.py` along with its module-level label constants and the PipelineEvent import. The class starts at line 52 and ends at line 325 of the original `github.py`. Use `Read` to get the exact range and transcribe it here.

**Copy-paste fidelity is critical.** Do not refactor, reformat, rename, or "clean up" anything during this step. Any content change invalidates the zero-behavior-change contract of this refactor. The only intentional edits are: (a) drop unused top-level imports that belonged only to `GitHubReviewAdapter`, (b) change the hardcoded logger name to `logging.getLogger(__name__)` so it tracks the new module path automatically.

File skeleton:

```python
"""GitHubWorkAdapter — WorkAdapter impl backed by GitHub Issues via PyGithub."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from github.Repository import Repository

from a2sdlc.adapters.work import PipelineEvent
from a2sdlc.domain.exceptions import SkipEvent
from a2sdlc.domain.handover import (
    HANDOVER_PATTERN,
    FeedbackItem,
    HandoverComment,
    parse_handover,
)
from a2sdlc.domain.models import StageName

logger = logging.getLogger(__name__)

# ── Label constants (used only by GitHubWorkAdapter) ──────────────────

STAGE_LABELS: dict[StageName, str] = {
    StageName.SPEC: "stage:spec",
    StageName.IMPLEMENT: "stage:implement",
    StageName.REVIEW: "stage:review",
    StageName.MERGE: "stage:merge",
}
_LABEL_TO_STAGE: dict[str, StageName] = {v: k for k, v in STAGE_LABELS.items()}

TRIGGER_LABEL = "agent"
BLOCKED_LABEL = "stage:blocked"
DONE_LABEL = "stage:done"
NEEDS_INPUT_LABEL = "needs-input"
PROCEED_LABEL = "proceed"


# ── GitHubWorkAdapter ─────────────────────────────────────────────────


class GitHubWorkAdapter:
    """WorkAdapter backed by GitHub Issues via PyGithub."""

    # ... (paste full class body from original github.py lines 52-325) ...


__all__ = ["GitHubWorkAdapter"]
```

Use `Read` on `src/a2sdlc/adapters/github.py:52-325` and paste the class body verbatim. Remove the `re` import if it's not used by the class body (verify after paste).

- [ ] **Step 2: Add `GitHubWorkAdapter` to `work/__init__.py` re-exports**

Append the import and extend `__all__`:
```python
from a2sdlc.adapters.work.github import GitHubWorkAdapter  # noqa: E402

__all__ = ["PipelineEvent", "WorkAdapter", "LocalFileWorkAdapter", "GitHubWorkAdapter"]
```

- [ ] **Step 3: Verify the module imports cleanly**

```bash
uv run python -c "from a2sdlc.adapters.work import GitHubWorkAdapter; print(GitHubWorkAdapter)"
```

Expected: prints class repr. Do NOT run `make check` yet — `github.py` still defines GitHubWorkAdapter too; both coexist briefly. That's only deleted in Task 2.4.

---

## Task 2.3: Carve out `review/github.py`

**Files:**
- Create: `src/a2sdlc/adapters/review/github.py` (GitHubReviewAdapter)
- Modify: `src/a2sdlc/adapters/review/__init__.py` (re-export GitHubReviewAdapter)

- [ ] **Step 1: Create `src/a2sdlc/adapters/review/github.py`**

Copy `GitHubReviewAdapter` from `src/a2sdlc/adapters/github.py:326-end`. Same fidelity rule as Task 2.2: no refactoring, renaming, or cleanup during this step. Only intentional edits: drop unused imports that belonged only to `GitHubWorkAdapter`, switch hardcoded logger to `__name__`.

Skeleton:

```python
"""GitHubReviewAdapter — ReviewAdapter impl backed by PyGithub."""

from __future__ import annotations

import logging
from datetime import datetime

from github.Repository import Repository

from a2sdlc.adapters.review import Approval, ReviewComment
from a2sdlc.domain.handover import (
    FeedbackItem,
    HandoverComment,
    parse_handover,
)

logger = logging.getLogger(__name__)


class GitHubReviewAdapter:
    """ReviewAdapter backed by PyGithub."""

    # ... (paste full class body from original github.py lines 326-end) ...


__all__ = ["GitHubReviewAdapter"]
```

Use `Read` on `src/a2sdlc/adapters/github.py:326-471` and paste the class body verbatim. Drop imports that aren't actually used by this half (e.g. `json`, `os`, `re`, `StageName`, `HANDOVER_PATTERN` — verify via grep before dropping).

- [ ] **Step 2: Add `GitHubReviewAdapter` to `review/__init__.py` re-exports**

Append:
```python
from a2sdlc.adapters.review.github import GitHubReviewAdapter  # noqa: E402

__all__ = ["Approval", "ReviewComment", "ReviewAdapter", "LocalNoopReviewAdapter", "GitHubReviewAdapter"]
```

- [ ] **Step 3: Verify the module imports cleanly**

```bash
uv run python -c "from a2sdlc.adapters.review import GitHubReviewAdapter; print(GitHubReviewAdapter)"
```

Expected: prints class repr.

---

## Task 2.4: Delete old `github.py`, update callers, commit

**Files:**
- Delete: `src/a2sdlc/adapters/github.py`
- Modify: `src/a2sdlc/cli.py:120-124` (update imports)
- Modify: `tests/adapters/test_github_work.py:9` (import path)
- Modify: `tests/adapters/test_github_review.py:9` (import path)
- Modify: `tests/adapters/test_github_parse_event.py:12` (import path)
- Modify: `tests/test_cli.py:211-213` (3 patch strings)

- [ ] **Step 1: Update `src/a2sdlc/cli.py`**

Replace:
```python
        from a2sdlc.adapters.github import (  # noqa: PLC0415
            GitHubReviewAdapter,
            GitHubWorkAdapter,
            connect,
        )
```
with:
```python
        from a2sdlc.adapters._github import connect  # noqa: PLC0415
        from a2sdlc.adapters.review import GitHubReviewAdapter  # noqa: PLC0415
        from a2sdlc.adapters.work import GitHubWorkAdapter  # noqa: PLC0415
```

- [ ] **Step 2: Update `tests/adapters/test_github_work.py:9`**

Replace:
```python
from a2sdlc.adapters.github import GitHubWorkAdapter
```
with:
```python
from a2sdlc.adapters.work.github import GitHubWorkAdapter
```

- [ ] **Step 3: Update `tests/adapters/test_github_review.py:9`**

Replace:
```python
from a2sdlc.adapters.github import GitHubReviewAdapter
```
with:
```python
from a2sdlc.adapters.review.github import GitHubReviewAdapter
```

- [ ] **Step 4: Update `tests/adapters/test_github_parse_event.py:12`**

Replace:
```python
from a2sdlc.adapters.github import GitHubWorkAdapter
```
with:
```python
from a2sdlc.adapters.work.github import GitHubWorkAdapter
```

- [ ] **Step 5: Update `tests/test_cli.py:211-213` patch strings**

Replace:
```python
            patch("a2sdlc.adapters.github.connect") as mock_connect,
            patch("a2sdlc.adapters.github.GitHubWorkAdapter") as mock_work,
            patch("a2sdlc.adapters.github.GitHubReviewAdapter") as mock_review,
```
with:
```python
            patch("a2sdlc.adapters._github.connect") as mock_connect,
            patch("a2sdlc.adapters.work.github.GitHubWorkAdapter") as mock_work,
            patch("a2sdlc.adapters.review.github.GitHubReviewAdapter") as mock_review,
```

- [ ] **Step 6: Delete old `adapters/github.py`**

```bash
git rm src/a2sdlc/adapters/github.py
```

- [ ] **Step 7: Run `make check`**

```bash
make check
```

Expected: all green.

- [ ] **Step 8: Verify no references to the old `adapters.github` module path**

```bash
rg -n 'a2sdlc\.adapters\.github\b' src tests docs/superpowers/specs
```

Expected: zero matches. (New paths contain `.work.github`, `.review.github`, or `._github` — the `\b` anchor excludes those.)

- [ ] **Step 9: Commit Commit 2**

```bash
git add -A
git commit -m "$(cat <<'EOF'
refactor(adapters): split github.py into work/ and review/ halves

The old adapters/github.py (471 lines) mixed GitHubWorkAdapter and
GitHubReviewAdapter in one file, which doesn't fit the kind-first
layout. Split into:

- adapters/work/github.py    — GitHubWorkAdapter + label constants
- adapters/review/github.py  — GitHubReviewAdapter
- adapters/_github.py        — shared connect() helper (underscore-prefixed,
                               not part of the public adapters surface)

Label constants (STAGE_LABELS, TRIGGER_LABEL, BLOCKED_LABEL, etc.) are
used only by the work adapter — they move with it, not into _github.py.

Updates cli.py to import the three pieces from their new homes.
Updates 4 test imports and 3 patch() strings in tests/test_cli.py.

Blame continuity on the split is lost for the one commit; git log
--follow still traces single-file renames in the rest of the tree.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3.1: Create `src/a2sdlc/domain/pipeline_event.py`

**Files:**
- Create: `src/a2sdlc/domain/pipeline_event.py`

- [ ] **Step 1: Create the domain module**

```python
"""PipelineEvent — normalized work-adapter event.

Pure dataclass; crosses the pipeline↔adapter boundary. Consumed by both
``pipeline/dispatch.py`` and every ``WorkAdapter.parse_event()`` impl.
Lives in ``domain/`` because it has no I/O dependencies and both layers
need it.
"""

from __future__ import annotations

from dataclasses import dataclass

from a2sdlc.domain.models import StageName


@dataclass
class PipelineEvent:
    """Normalized pipeline event from a work adapter.

    trigger_stage: what the event literally says (label value, or None for feedback/proceed).
    is_feedback: True for comment/review events, False for label events.
    The engine resolves the actual target stage via the routing table.
    """

    key: str
    trigger_stage: StageName | None = None
    is_feedback: bool = False
    pr_number: int | None = None


__all__ = ["PipelineEvent"]
```

- [ ] **Step 2: Verify the new module is importable**

```bash
uv run python -c "from a2sdlc.domain.pipeline_event import PipelineEvent; print(PipelineEvent)"
```

Expected: prints class repr.

---

## Task 3.2: Update all import sites to point at `domain/`

**Files:**
- Modify: `src/a2sdlc/adapters/work/__init__.py` (remove `PipelineEvent` definition; re-import from domain)
- Modify: `src/a2sdlc/adapters/work/github.py` (update `PipelineEvent` import)
- Modify: `src/a2sdlc/adapters/work/local_file.py` (update `PipelineEvent` import)
- Modify: `src/a2sdlc/adapters/__init__.py` (drop PipelineEvent re-export)
- Modify: `src/a2sdlc/pipeline/dispatch.py` (update `PipelineEvent` import)
- Modify: `tests/fakes.py` (update `PipelineEvent` import)
- Modify: `tests/pipeline/test_dispatch.py` (update `PipelineEvent` import)
- Modify: `tests/pipeline/test_dispatch_e2e.py` (update `PipelineEvent` import)
- Modify: `tests/pipeline/test_dispatch_progress.py` (update `PipelineEvent` import)
- Modify: `tests/adapters/test_gh_comment_subscriber.py:108` (update lazy PipelineEvent import)
- Modify: `tests/lifecycle/test_comment.py:185` (update lazy PipelineEvent import)

- [ ] **Step 1: Update `src/a2sdlc/adapters/work/__init__.py`**

Remove the `PipelineEvent` dataclass definition. Keep `WorkAdapter`. The `__init__.py` now imports `PipelineEvent` from `domain` for backward-compatibility re-export:

```python
"""WorkAdapter Protocol + in-tree work impls.

Note: ``PipelineEvent`` moved to ``a2sdlc.domain.pipeline_event`` in the
adapters-layout refactor. This module re-exports it for backward
compatibility with callers that used ``from a2sdlc.adapters.work import
PipelineEvent``. New code should import directly from domain.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from a2sdlc.domain.handover import FeedbackItem, HandoverComment
from a2sdlc.domain.models import StageName
from a2sdlc.domain.pipeline_event import PipelineEvent


class WorkAdapter(Protocol):
    """Platform-specific ticket/work-item operations."""

    def parse_event(self) -> PipelineEvent: ...
    def get_ticket(self, key: str) -> str: ...
    def get_labels(self, key: str) -> list[str]: ...
    def begin_comment(self, key: str) -> str: ...
    def update_progress(self, comment_id: str, body: str) -> None: ...
    def finalize_comment(self, comment_id: str, body: str) -> None: ...
    def set_stage_label(self, key: str, stage: StageName) -> None: ...
    def set_done_label(self, key: str) -> None: ...
    def set_blocked(self, key: str, reason: str) -> None: ...
    def format_branch(self, ticket_key: str) -> str: ...
    def collect_issue_feedback(
        self, key: str, since: datetime
    ) -> list[FeedbackItem]: ...
    def find_last_handover(self, key: str) -> HandoverComment | None: ...


from a2sdlc.adapters.work.github import GitHubWorkAdapter  # noqa: E402
from a2sdlc.adapters.work.local_file import LocalFileWorkAdapter  # noqa: E402

__all__ = [
    "PipelineEvent",
    "WorkAdapter",
    "LocalFileWorkAdapter",
    "GitHubWorkAdapter",
]
```

- [ ] **Step 2: Update `work/github.py` PipelineEvent import**

Replace:
```python
from a2sdlc.adapters.work import PipelineEvent
```
with:
```python
from a2sdlc.domain.pipeline_event import PipelineEvent
```

- [ ] **Step 3: Update `work/local_file.py` PipelineEvent import**

Replace:
```python
from a2sdlc.adapters.work import PipelineEvent
```
with:
```python
from a2sdlc.domain.pipeline_event import PipelineEvent
```

- [ ] **Step 4: Update `src/a2sdlc/adapters/__init__.py`**

Remove `PipelineEvent` from the re-export list. After edit:

```python
"""Adapter registry."""

from __future__ import annotations

from a2sdlc.adapters.git import GitAdapter
from a2sdlc.adapters.review import Approval, ReviewAdapter, ReviewComment
from a2sdlc.adapters.runner import StageRunner
from a2sdlc.adapters.work import WorkAdapter

__all__ = [
    "GitAdapter",
    "StageRunner",
    "WorkAdapter",
    "Approval",
    "ReviewComment",
    "ReviewAdapter",
]
```

- [ ] **Step 5: Confirm `dispatch.py` does not need a direct `PipelineEvent` import**

Verified 2026-04-19 via grep: `src/a2sdlc/pipeline/dispatch.py` does not reference `PipelineEvent` directly — the type flows through `WorkAdapter.parse_event()`'s return. No change needed in this file.

Sanity-check by re-running the grep before editing:
```bash
grep -n "PipelineEvent" src/a2sdlc/pipeline/dispatch.py
```
Expected: no matches. If matches appear (unrelated work landed), add `from a2sdlc.domain.pipeline_event import PipelineEvent` to the imports block.

- [ ] **Step 6: Update `tests/fakes.py`**

Replace:
```python
from a2sdlc.adapters.work import PipelineEvent
```
with:
```python
from a2sdlc.domain.pipeline_event import PipelineEvent
```

- [ ] **Step 7: Update `tests/pipeline/test_dispatch.py`**

Replace:
```python
from a2sdlc.adapters.work import PipelineEvent
```
with:
```python
from a2sdlc.domain.pipeline_event import PipelineEvent
```

- [ ] **Step 7b: Update `tests/pipeline/test_dispatch_e2e.py`**

Replace:
```python
from a2sdlc.adapters.work import PipelineEvent
```
with:
```python
from a2sdlc.domain.pipeline_event import PipelineEvent
```

- [ ] **Step 7c: Update `tests/pipeline/test_dispatch_progress.py`**

Replace:
```python
from a2sdlc.adapters.work import PipelineEvent
```
with:
```python
from a2sdlc.domain.pipeline_event import PipelineEvent
```

- [ ] **Step 8: Update `tests/adapters/test_gh_comment_subscriber.py:108` (lazy import)**

Replace:
```python
    from a2sdlc.adapters.work import PipelineEvent
```
with:
```python
    from a2sdlc.domain.pipeline_event import PipelineEvent
```

- [ ] **Step 9: Update `tests/lifecycle/test_comment.py:185` (lazy import)**

Replace:
```python
    from a2sdlc.adapters.work import PipelineEvent
```
with:
```python
    from a2sdlc.domain.pipeline_event import PipelineEvent
```

- [ ] **Step 10: Verify the domain purity contract still holds**

```bash
uv run lint-imports
```

Expected: the "domain is pure (no imports from other a2sdlc packages)" contract passes. The new `domain/pipeline_event.py` only imports from `a2sdlc.domain.models`, which is inside `domain/` — compliant.

---

## Task 3.3: Move test file and commit Commit 3

**Files:**
- Create: `tests/domain/` directory (if it doesn't exist)
- Move: `tests/adapters/test_pipeline_event.py` → `tests/domain/test_pipeline_event.py`
- Modify: `tests/domain/test_pipeline_event.py:5` (import path)

- [ ] **Step 1: Create `tests/domain/` if it doesn't exist**

```bash
mkdir -p tests/domain
touch tests/domain/__init__.py
```

Check if `tests/domain/__init__.py` already exists (other domain tests may live there):
```bash
ls tests/domain/ 2>&1
```

If it doesn't exist, `touch` creates the empty init file matching the convention.

- [ ] **Step 2: Move the test file**

```bash
git mv tests/adapters/test_pipeline_event.py tests/domain/test_pipeline_event.py
```

- [ ] **Step 3: Update the moved file's import**

Replace in `tests/domain/test_pipeline_event.py`:
```python
from a2sdlc.adapters.work import PipelineEvent
```
with:
```python
from a2sdlc.domain.pipeline_event import PipelineEvent
```

- [ ] **Step 4: Run `make check`**

```bash
make check
```

Expected: all green.

- [ ] **Step 5: Verify PipelineEvent fully migrated**

```bash
rg -n 'from a2sdlc\.adapters.*PipelineEvent' src tests
```

Expected: zero matches.

- [ ] **Step 6: Commit Commit 3**

```bash
git add -A
git commit -m "$(cat <<'EOF'
refactor(domain): move PipelineEvent from adapters/work to domain/

PipelineEvent is a pure dataclass with no I/O that crosses the
pipeline↔adapter boundary — every WorkAdapter.parse_event() impl
returns it, and pipeline/dispatch.py consumes it. Belongs in domain/
alongside models.py, run_result.py, and the other pure types.

adapters/work/__init__.py keeps re-exporting PipelineEvent for
backward compatibility with callers that used the old import path.
All src/ and tests/ call sites updated to import from
a2sdlc.domain.pipeline_event directly.

The test also moves: tests/adapters/test_pipeline_event.py →
tests/domain/test_pipeline_event.py to track the type's new home.

Domain-purity import-linter contract verified — pipeline_event.py
only imports from a2sdlc.domain.models, which is inside domain/.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4.1: Create test subfolders

**Files:**
- Create: `tests/adapters/git/__init__.py`
- Create: `tests/adapters/work/__init__.py`
- Create: `tests/adapters/review/__init__.py`
- Create: `tests/adapters/subscriber/__init__.py`

Empty `__init__.py`s match the existing `tests/adapters/__init__.py` convention.

- [ ] **Step 1: Create all four empty init files**

```bash
mkdir -p tests/adapters/git tests/adapters/work tests/adapters/review tests/adapters/subscriber
touch tests/adapters/git/__init__.py
touch tests/adapters/work/__init__.py
touch tests/adapters/review/__init__.py
touch tests/adapters/subscriber/__init__.py
```

- [ ] **Step 2: Run `make check` to confirm no test-discovery regression**

```bash
make check
```

Expected: all green. (Empty init files don't change anything yet — the tests still live at the old paths.)

---

## Task 4.2: Move test files to mirror src/ layout

**Files moved (13 total):**

git/ (2):
- `tests/adapters/test_git.py` → `tests/adapters/git/test_local.py`
- `tests/adapters/test_local_branch_git.py` → `tests/adapters/git/test_local_branch.py`

work/ (3):
- `tests/adapters/test_github_work.py` → `tests/adapters/work/test_github.py`
- `tests/adapters/test_github_parse_event.py` → `tests/adapters/work/test_github_parse_event.py`
- `tests/adapters/test_local_file_work.py` → `tests/adapters/work/test_local_file.py`

review/ (2):
- `tests/adapters/test_github_review.py` → `tests/adapters/review/test_github.py`
- `tests/adapters/test_local_noop_review.py` → `tests/adapters/review/test_local_noop.py`

subscriber/ (5):
- `tests/adapters/test_console_subscriber.py` → `tests/adapters/subscriber/test_console.py`
- `tests/adapters/test_gh_actions_subscriber.py` → `tests/adapters/subscriber/test_gh_actions.py`
- `tests/adapters/test_gh_comment_subscriber.py` → `tests/adapters/subscriber/test_gh_comment.py`
- `tests/adapters/test_mlflow_trace_subscriber.py` → `tests/adapters/subscriber/test_mlflow_trace.py`
- `tests/adapters/test_subscriber_protocol.py` → `tests/adapters/subscriber/test_protocol.py`

Staying flat:
- `tests/adapters/test_factory.py`, `tests/adapters/test_retry.py`, `tests/adapters/test_pipeline_event.py` (already moved to `tests/domain/` in Task 3.3).

- [ ] **Step 1: Move all 13 files with `git mv`**

```bash
cd /Users/iorlas/Workspaces/a2sdlc-engine

git mv tests/adapters/test_git.py                    tests/adapters/git/test_local.py
git mv tests/adapters/test_local_branch_git.py       tests/adapters/git/test_local_branch.py

git mv tests/adapters/test_github_work.py            tests/adapters/work/test_github.py
git mv tests/adapters/test_github_parse_event.py     tests/adapters/work/test_github_parse_event.py
git mv tests/adapters/test_local_file_work.py        tests/adapters/work/test_local_file.py

git mv tests/adapters/test_github_review.py          tests/adapters/review/test_github.py
git mv tests/adapters/test_local_noop_review.py      tests/adapters/review/test_local_noop.py

git mv tests/adapters/test_console_subscriber.py     tests/adapters/subscriber/test_console.py
git mv tests/adapters/test_gh_actions_subscriber.py  tests/adapters/subscriber/test_gh_actions.py
git mv tests/adapters/test_gh_comment_subscriber.py  tests/adapters/subscriber/test_gh_comment.py
git mv tests/adapters/test_mlflow_trace_subscriber.py tests/adapters/subscriber/test_mlflow_trace.py
git mv tests/adapters/test_subscriber_protocol.py    tests/adapters/subscriber/test_protocol.py
```

- [ ] **Step 2: Verify the new layout**

```bash
ls tests/adapters/
ls tests/adapters/git/
ls tests/adapters/work/
ls tests/adapters/review/
ls tests/adapters/subscriber/
```

Expected: `tests/adapters/` root shows `__init__.py`, `test_factory.py`, `test_retry.py`, and the four new subfolders. Each subfolder shows its `__init__.py` plus the moved test files.

- [ ] **Step 3: Run `make check`**

```bash
make check
```

Expected: all green. Test discovery finds tests at their new nested paths automatically (pytest walks directories).

---

## Task 4.3: Final grep sweep + commit Commit 4

- [ ] **Step 1: Verify no stale `patch()` strings remain**

```bash
rg -n 'patch\(["'\'']a2sdlc\.adapters\.(protocols|console_subscriber|gh_actions_subscriber|gh_comment_subscriber|mlflow_trace_subscriber|local_branch_git|local_file_work|local_noop_review|github)\b' tests src
```

Expected: zero matches.

- [ ] **Step 2: Verify no stale `logger=` strings**

```bash
rg -n 'logger=["'\'']a2sdlc\.adapters\.(local_file_work|github|local_noop_review)\b' tests src
```

Expected: zero matches.

- [ ] **Step 3: Verify no references to fully-renamed flat modules**

```bash
rg -n 'a2sdlc\.adapters\.(protocols|console_subscriber|gh_actions_subscriber|gh_comment_subscriber|mlflow_trace_subscriber|local_branch_git|local_file_work|local_noop_review)\b' src tests docs/superpowers/specs
```

Expected: zero matches.

- [ ] **Step 4: Verify no direct references to old flat `adapters.github` module**

```bash
rg -n 'a2sdlc\.adapters\.github\b' src tests docs/superpowers/specs
```

Expected: zero matches. (Paths like `a2sdlc.adapters.work.github` and `a2sdlc.adapters.review.github` are excluded by `\b`.)

- [ ] **Step 5: Verify PipelineEvent lives only in domain/**

```bash
rg -n 'from a2sdlc\.adapters.*PipelineEvent' src tests
```

Expected: zero matches.

- [ ] **Step 6: Verify Protocol file count**

```bash
find src/a2sdlc/adapters -name '*.py' | xargs grep -l 'class.*Protocol' | sort
```

Expected output (exactly 5 files):
```
src/a2sdlc/adapters/git/__init__.py
src/a2sdlc/adapters/review/__init__.py
src/a2sdlc/adapters/runner/__init__.py
src/a2sdlc/adapters/subscriber/__init__.py
src/a2sdlc/adapters/work/__init__.py
```

No `protocols.py`, no `work.py`, no `review.py` in results.

- [ ] **Step 7: Verify test count matches baseline**

```bash
uv run pytest --tb=no -q 2>&1 | tail -3
```

Expected: test count equals the baseline recorded in Task 0. If fewer, a file was accidentally dropped during moves — investigate with `git log --follow` before continuing.

- [ ] **Step 8: Update the in-progress spec that references old subscriber path**

`docs/superpowers/specs/2026-04-18-transcript-log-subscriber-design.md` references `adapters.mlflow_trace_subscriber` — update to the new path.

Replace in that file:
```
from a2sdlc.adapters.mlflow_trace_subscriber import MlflowTraceSubscriber
```
with:
```
from a2sdlc.adapters.subscriber.mlflow_trace import MlflowTraceSubscriber
```

Use `Edit` tool on the spec file. There's one occurrence (around line 134). Executed plan docs in `docs/superpowers/plans/` stay as history — do NOT touch them.

- [ ] **Step 9: Run `make check` one more time**

```bash
make check
```

Expected: all green.

- [ ] **Step 10: Commit Commit 4**

```bash
git add -A
git commit -m "$(cat <<'EOF'
refactor(tests): mirror adapters kind-first layout in tests/adapters

Move 12 test files into kind subfolders matching the new src/ layout:

- tests/adapters/git/       — test_local.py, test_local_branch.py
- tests/adapters/work/      — test_github.py, test_github_parse_event.py,
                              test_local_file.py
- tests/adapters/review/    — test_github.py, test_local_noop.py
- tests/adapters/subscriber/ — test_console.py, test_gh_actions.py,
                              test_gh_comment.py, test_mlflow_trace.py,
                              test_protocol.py

Rename test_subscriber_protocol.py → test_protocol.py — the old name
implied it covered multiple protocols, but it only tests Subscriber.

Keep top-level: test_factory.py and test_retry.py are cross-kind, they
don't fit one subfolder. test_pipeline_event.py already moved to
tests/domain/ with PipelineEvent in commit 3.

Final sweep greps for stale module-path strings — zero hits.

Also updates the live TranscriptLogSubscriber spec's module path
reference to the new subscriber.mlflow_trace path. Executed plan docs
are left as history.

Zero behavior change. Test count preserved.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 11: Final branch verification**

```bash
git log --oneline main..HEAD
```

Expected: 4 commits, one per migration phase, each with a `refactor(...)` prefix.

```bash
git diff --stat main
```

Expected: a diff showing files renamed (git-mv detection) and small edits to protocol definitions, imports, and patch strings. No unexpected content changes.

---

## Acceptance checklist

Tick these before declaring the plan complete:

- [ ] All 4 commits landed on `feat/adapters-layout`
- [ ] `make check` green at HEAD
- [ ] Test count at HEAD equals baseline from Task 0 Step 3
- [ ] Protocol-file-count check (Task 4.3 Step 6) returns exactly the 5 expected paths
- [ ] All grep sweeps in Task 4.3 return zero matches
- [ ] `git log --oneline main..HEAD` shows 4 `refactor(...)` commits
- [ ] Branch pushed (or PR'd) per current branch-management flow

## Rollback

If any commit boundary can't reach green within ~30 minutes of debugging:

```bash
git reset --hard main
# start over with the next attempt, referencing spec line-by-line
```

The plan is structured so each `make check` green is a safe rollback point. Prefer `git reset --hard <sha>` to the last green commit over hunting for bugs in an incomplete state.
