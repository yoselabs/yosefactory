# a2sdlc Local Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the offline-adapter local runner described in `docs/superpowers/specs/2026-04-18-a2sdlc-local-runner-design.md` (revision 4): a per-stage CLI that runs the a2sdlc pipeline locally against any repo, with MLflow metrics, quality gate, and live console UX.

**Architecture:** Adapter-selected implementations wired through existing ports. Engine code paths (`pipeline/*`, `stages/*`, `domain/*`, `lifecycle/*`, `assembly/*`) are unchanged. New local adapters persist all engine-required state (ticket body, handover, PR mock, feedback, TicketState) as files under `.a2sdlc/` on a session branch `a2sdlc/<session_id>`.

**Tech Stack:** Python 3.12, pytest, rich, pyyaml, gitpython, claude-agent-sdk, mlflow (new dep), pydantic.

---

## File Structure

**Created:**
- `src/a2sdlc/adapters/local_file_work.py` — full `WorkAdapter` impl (file-backed handover)
- `src/a2sdlc/adapters/local_noop_review.py` — full `ReviewAdapter` impl (file-backed PR mock)
- `src/a2sdlc/adapters/local_branch_git.py` — `GitAdapter` override (no origin fetch)
- `src/a2sdlc/adapters/progress_console.py` — `rich.Live` console renderer
- `src/a2sdlc/adapters/progress_gh_actions.py` — extracted `::group::` renderer
- `src/a2sdlc/evaluation/mlflow_sink.py` — MLflow tracking wrapper
- `src/a2sdlc/evaluation/quality_gate.py` — post-implement quality check
- `src/a2sdlc/cli_local.py` — internals for `run-stage` subcommand (keeps `cli.py` small)
- `tests/adapters/test_local_file_work.py`
- `tests/adapters/test_local_noop_review.py`
- `tests/adapters/test_local_branch_git.py`
- `tests/adapters/test_progress_console.py`
- `tests/evaluation/test_mlflow_sink.py`
- `tests/evaluation/test_quality_gate.py`
- `tests/test_cli_local.py`
- `tests/integration/test_local_runner_e2e.py`

**Modified:**
- `src/a2sdlc/adapters/protocols.py` — add `ProgressAdapter` protocol
- `src/a2sdlc/config.py` — migrate path to `.a2sdlc/config.yaml`, strict unknown-key rejection, `adapters:` block, `quality.check_command`
- `src/a2sdlc/pipeline/runner.py` — accept `ProgressAdapter`, remove hardcoded `::group::`/`print` calls
- `src/a2sdlc/evaluation/progress.py` — delegate rendering to `ProgressAdapter`
- `src/a2sdlc/cli.py` — add `run-stage` subcommand dispatching to `cli_local`
- `pyproject.toml` — add `mlflow` dep
- `tests/fakes.py` — add `FakeProgressAdapter`

**Out of scope for this plan:** Jira adapter refactor to new port shape (only needed if protocol must widen; see Task 1 note).

---

## Convention Notes

- **Tests are behavior-named.** Use `test_<component>_<given>_<when>_<then>` or add a `"""GIVEN / WHEN / THEN"""` docstring. We don't use Gherkin files; pytest is the harness.
- **Use `make` commands** — `make test`, `make lint`, `make check` — not raw `uv run pytest`.
- **Commit after each task** completes successfully. Message format: `feat(local): <what>` or `refactor(local): <what>` or `test(local): <what>`.
- **Never commit failing tests** — run `make test` before every commit.

---

## Task 1: Config migration — new path and strict key validation

**Files:**
- Modify: `src/a2sdlc/config.py`
- Modify: `tests/test_config.py`
- Create sample: `tests/fixtures/local_config.yaml`

**What changes:** The config loader currently reads `a2sdlc.yaml` at project root (see `config.py:67`) and silently ignores unknown keys. Move to `.a2sdlc/config.yaml`, reject unknown top-level keys, and add an `adapters:` block plus `quality.check_command`.

- [ ] **Step 1: Write the failing test for new config path**

Add to `tests/test_config.py`:

```python
def test_load_config_reads_from_a2sdlc_subdir(tmp_path):
    """GIVEN a repo with .a2sdlc/config.yaml
    WHEN load_config_file is called with the repo path
    THEN the config is loaded from that file."""
    a2sdlc_dir = tmp_path / ".a2sdlc"
    a2sdlc_dir.mkdir()
    (a2sdlc_dir / "config.yaml").write_text("model: claude-sonnet-4-6\n")

    from a2sdlc.config import load_config_file
    cfg = load_config_file(tmp_path)

    assert cfg.model == "claude-sonnet-4-6"
```

- [ ] **Step 2: Run the test — it should fail (old path)**

Run: `make test TEST=tests/test_config.py::test_load_config_reads_from_a2sdlc_subdir`
Expected: FAIL — loader still reads `a2sdlc.yaml`.

- [ ] **Step 3: Update `config.py` to read from new path**

Edit `src/a2sdlc/config.py`:

```python
def load_config_file(project_root: Path) -> Config:
    """Load config from .a2sdlc/config.yaml in project_root."""
    config_path = project_root / ".a2sdlc" / "config.yaml"
    if not config_path.is_file():
        raise FileNotFoundError(
            f"Config not found at {config_path}. "
            f"Create .a2sdlc/config.yaml — see docs/superpowers/specs/"
            f"2026-04-18-a2sdlc-local-runner-design.md for schema."
        )
    # ...rest unchanged (yaml.safe_load + Config construction)
```

- [ ] **Step 4: Run the test again — expect PASS**

Run: `make test TEST=tests/test_config.py::test_load_config_reads_from_a2sdlc_subdir`
Expected: PASS.

- [ ] **Step 5: Write failing test for strict unknown-key rejection**

```python
def test_load_config_rejects_unknown_top_level_keys(tmp_path):
    """GIVEN a config with a typo'd top-level key
    WHEN loaded
    THEN raises ConfigError listing the unknown key."""
    a2sdlc_dir = tmp_path / ".a2sdlc"
    a2sdlc_dir.mkdir()
    (a2sdlc_dir / "config.yaml").write_text("modell: x\n")  # typo

    from a2sdlc.config import load_config_file, ConfigError
    import pytest
    with pytest.raises(ConfigError, match="modell"):
        load_config_file(tmp_path)
```

- [ ] **Step 6: Add `ConfigError` and strict validation**

Add to `config.py`:

```python
class ConfigError(ValueError):
    """Raised when config file is malformed or has unknown keys."""

_ALLOWED_TOP_LEVEL_KEYS = {"adapters", "stages", "spec", "quality", "model",
                           "default_base", "max_turns_per_stage", "gates",
                           "self_answer", "resume", "timeouts"}

def _validate_keys(data: dict) -> None:
    unknown = set(data.keys()) - _ALLOWED_TOP_LEVEL_KEYS
    if unknown:
        raise ConfigError(f"Unknown config keys: {sorted(unknown)}")
```

Call `_validate_keys(data)` in `load_config_file` after `yaml.safe_load`.

- [ ] **Step 7: Write failing test for `adapters:` block**

```python
def test_load_config_parses_adapters_block(tmp_path):
    """GIVEN a config with adapters: {work, review, git, progress}
    WHEN loaded
    THEN Config.adapters holds those four names."""
    a2sdlc_dir = tmp_path / ".a2sdlc"
    a2sdlc_dir.mkdir()
    (a2sdlc_dir / "config.yaml").write_text(
        "adapters:\n  work: local_file\n  review: local_noop\n"
        "  git: local_branch\n  progress: console\n"
    )
    from a2sdlc.config import load_config_file
    cfg = load_config_file(tmp_path)
    assert cfg.adapters.work == "local_file"
    assert cfg.adapters.review == "local_noop"
    assert cfg.adapters.git == "local_branch"
    assert cfg.adapters.progress == "console"
```

- [ ] **Step 8: Add `AdaptersConfig` and `QualityConfig` to `config.py`**

```python
@dataclass(frozen=True)
class AdaptersConfig:
    work: str = "jira"
    review: str = "github"
    git: str = "github"
    progress: str = "gh_actions"

@dataclass(frozen=True)
class QualityConfig:
    check_command: str = "make check"

# In Config:
adapters: AdaptersConfig = field(default_factory=AdaptersConfig)
quality: QualityConfig = field(default_factory=QualityConfig)
```

Parse both in `load_config_file` with `**data.get("adapters", {})` / `**data.get("quality", {})`.

- [ ] **Step 9: Run all config tests**

Run: `make test TEST=tests/test_config.py`
Expected: all green.

- [ ] **Step 10: Run linter to catch anything broken**

Run: `make lint`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add src/a2sdlc/config.py tests/test_config.py tests/fixtures/local_config.yaml
git commit -m "feat(config): migrate to .a2sdlc/config.yaml with strict keys and adapters block"
```

---

## Task 2: Add `ProgressAdapter` protocol

**Files:**
- Modify: `src/a2sdlc/adapters/protocols.py`
- Modify: `tests/adapters/test_protocols.py` (create if missing)

**What changes:** The engine currently has hardcoded `print("::group::...")` calls in `pipeline/runner.py:228`. We introduce a `ProgressAdapter` port so rendering can be pluggable. This task only adds the protocol — the refactor of `runner.py` happens in Task 9.

- [ ] **Step 1: Write a test asserting the protocol shape**

Create `tests/adapters/test_protocols.py`:

```python
"""Smoke test that ProgressAdapter protocol is defined and structurally correct."""

from a2sdlc.adapters.protocols import ProgressAdapter


def test_progress_adapter_has_expected_methods():
    """GIVEN the ProgressAdapter protocol
    WHEN inspected
    THEN it declares on_stage_start, on_event, on_stage_end, on_group_open, on_group_close."""
    required = {"on_stage_start", "on_event", "on_stage_end", "on_group_open", "on_group_close"}
    declared = {name for name in dir(ProgressAdapter) if not name.startswith("_")}
    assert required.issubset(declared)
```

- [ ] **Step 2: Run — expect ImportError / AttributeError**

Run: `make test TEST=tests/adapters/test_protocols.py`
Expected: FAIL.

- [ ] **Step 3: Add `ProgressAdapter` to `protocols.py`**

Append to `src/a2sdlc/adapters/protocols.py`:

```python
from a2sdlc.domain.models import StageName


class ProgressAdapter(Protocol):
    """Render live progress events from the pipeline."""

    def on_stage_start(self, stage: StageName, session_id: str) -> None: ...
    def on_event(self, event_type: str, text: str) -> None: ...
    def on_stage_end(self, stage: StageName, success: bool) -> None: ...
    def on_group_open(self, title: str) -> None: ...
    def on_group_close(self) -> None: ...
```

Add `ProgressAdapter` to the file's `__all__` if present.

- [ ] **Step 4: Run test — expect PASS**

Run: `make test TEST=tests/adapters/test_protocols.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/a2sdlc/adapters/protocols.py tests/adapters/test_protocols.py
git commit -m "feat(adapters): add ProgressAdapter protocol"
```

---

## Task 3: Extract `progress_gh_actions` adapter from existing renderer

**Files:**
- Create: `src/a2sdlc/adapters/progress_gh_actions.py`
- Create: `tests/adapters/test_progress_gh_actions.py`

**What changes:** Current GH Actions `::group::` output lives inline in `pipeline/runner.py:228-233` and `pipeline/dispatch.py:255-257`. Extract this rendering into a dedicated adapter that implements `ProgressAdapter`. This task creates the adapter; wiring into the engine happens in Task 9.

- [ ] **Step 1: Write failing test**

Create `tests/adapters/test_progress_gh_actions.py`:

```python
"""Behavior test for GH Actions progress adapter."""

from a2sdlc.adapters.progress_gh_actions import GhActionsProgressAdapter
from a2sdlc.domain.models import StageName


def test_gh_actions_adapter_emits_group_markers(capsys):
    """GIVEN a GH Actions progress adapter
    WHEN a group is opened and closed
    THEN ::group:: and ::endgroup:: are printed."""
    adapter = GhActionsProgressAdapter()
    adapter.on_group_open("Agent output (123 chars)")
    adapter.on_group_close()

    out = capsys.readouterr().out
    assert "::group::Agent output (123 chars)" in out
    assert "::endgroup::" in out


def test_gh_actions_adapter_forwards_event_text(capsys):
    """GIVEN an event with text
    WHEN on_event is called
    THEN the text is printed."""
    adapter = GhActionsProgressAdapter()
    adapter.on_event("tool_use", "Read(/path/to/file)")
    out = capsys.readouterr().out
    assert "Read(/path/to/file)" in out
```

- [ ] **Step 2: Run — expect ImportError**

Run: `make test TEST=tests/adapters/test_progress_gh_actions.py`
Expected: FAIL.

- [ ] **Step 3: Implement `progress_gh_actions.py`**

Create `src/a2sdlc/adapters/progress_gh_actions.py`:

```python
"""GitHub Actions progress adapter — emits ::group:: / ::endgroup:: markers."""

from __future__ import annotations

import sys

from a2sdlc.domain.models import StageName


class GhActionsProgressAdapter:
    """Prints events as plain lines, with ::group:: markers for logical blocks."""

    def on_stage_start(self, stage: StageName, session_id: str) -> None:
        print(f"::group::Stage {stage.value} (session {session_id})", file=sys.stdout)  # noqa: T201

    def on_event(self, event_type: str, text: str) -> None:
        print(f"[{event_type}] {text}", file=sys.stdout)  # noqa: T201

    def on_stage_end(self, stage: StageName, success: bool) -> None:
        status = "OK" if success else "FAIL"
        print(f"Stage {stage.value} end: {status}", file=sys.stdout)  # noqa: T201
        print("::endgroup::", file=sys.stdout)  # noqa: T201

    def on_group_open(self, title: str) -> None:
        print(f"::group::{title}", file=sys.stdout)  # noqa: T201

    def on_group_close(self) -> None:
        print("::endgroup::", file=sys.stdout)  # noqa: T201
```

- [ ] **Step 4: Run — expect PASS**

Run: `make test TEST=tests/adapters/test_progress_gh_actions.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/a2sdlc/adapters/progress_gh_actions.py tests/adapters/test_progress_gh_actions.py
git commit -m "feat(adapters): add GhActionsProgressAdapter (extract ::group:: rendering)"
```

---

## Task 4: `progress_console` adapter with `rich.Live`

**Files:**
- Create: `src/a2sdlc/adapters/progress_console.py`
- Create: `tests/adapters/test_progress_console.py`

**What changes:** Implements the console renderer described in the spec's Live Console UX section: top pane scrolls events, bottom pane shows a persistent status bar with tokens/cost/turns/elapsed.

- [ ] **Step 1: Write behavior tests**

Create `tests/adapters/test_progress_console.py`:

```python
"""Behavior tests for console progress adapter.

Rich.Live is not captured well by capsys; we test the adapter's internal
state instead. Visual inspection happens during integration tests.
"""

from a2sdlc.adapters.progress_console import ConsoleProgressAdapter
from a2sdlc.domain.models import StageName


def test_console_adapter_tracks_active_stage():
    """GIVEN a console adapter
    WHEN on_stage_start fires
    THEN the adapter records the active stage and session id."""
    adapter = ConsoleProgressAdapter()
    adapter.on_stage_start(StageName.SPEC, "01HX123")
    assert adapter.active_stage == StageName.SPEC
    assert adapter.session_id == "01HX123"


def test_console_adapter_appends_events_to_log():
    """GIVEN a running adapter
    WHEN on_event fires multiple times
    THEN events accumulate in the scroll buffer."""
    adapter = ConsoleProgressAdapter()
    adapter.on_stage_start(StageName.SPEC, "sid")
    adapter.on_event("tool_use", "Read(foo.py)")
    adapter.on_event("text", "Analyzing...")
    assert len(adapter.recent_events) == 2
    assert "Read(foo.py)" in adapter.recent_events[0]


def test_console_adapter_update_metrics():
    """GIVEN a stage in progress
    WHEN metrics are updated
    THEN the status bar reflects them."""
    adapter = ConsoleProgressAdapter()
    adapter.on_stage_start(StageName.IMPLEMENT, "sid")
    adapter.update_metrics(tokens_in=1000, tokens_out=500, cost_usd=0.03, turns=2)
    status = adapter.render_status_bar()
    assert "1000" in status
    assert "0.03" in status
    assert "turns: 2" in status or "2" in status
```

- [ ] **Step 2: Run — expect ImportError**

Run: `make test TEST=tests/adapters/test_progress_console.py`
Expected: FAIL.

- [ ] **Step 3: Implement `progress_console.py`**

Create `src/a2sdlc/adapters/progress_console.py`:

```python
"""Console progress adapter using rich.Live for local mode."""

from __future__ import annotations

import time
from collections import deque

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from a2sdlc.domain.models import StageName


class ConsoleProgressAdapter:
    """Live console renderer: scrolling events on top, status bar on bottom."""

    _MAX_EVENTS = 20

    def __init__(self) -> None:
        self.active_stage: StageName | None = None
        self.session_id: str = ""
        self.recent_events: deque[str] = deque(maxlen=self._MAX_EVENTS)
        self._tokens_in = 0
        self._tokens_out = 0
        self._cost_usd = 0.0
        self._turns = 0
        self._started_at: float | None = None
        self._live: Live | None = None
        self._console = Console()

    def on_stage_start(self, stage: StageName, session_id: str) -> None:
        self.active_stage = stage
        self.session_id = session_id
        self._started_at = time.monotonic()
        self._live = Live(self._render(), console=self._console, refresh_per_second=1)
        self._live.__enter__()

    def on_event(self, event_type: str, text: str) -> None:
        line = f"[{event_type}] {text}"
        self.recent_events.append(line)
        if self._live:
            self._live.update(self._render())

    def on_stage_end(self, stage: StageName, success: bool) -> None:
        if self._live:
            self._live.__exit__(None, None, None)
            self._live = None

    def on_group_open(self, title: str) -> None:
        self.recent_events.append(f"▶ {title}")
        if self._live:
            self._live.update(self._render())

    def on_group_close(self) -> None:
        self.recent_events.append("◀ end")
        if self._live:
            self._live.update(self._render())

    def update_metrics(
        self, tokens_in: int, tokens_out: int, cost_usd: float, turns: int
    ) -> None:
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self._cost_usd = cost_usd
        self._turns = turns
        if self._live:
            self._live.update(self._render())

    def render_status_bar(self) -> str:
        elapsed = 0 if self._started_at is None else int(time.monotonic() - self._started_at)
        stage_name = self.active_stage.value if self.active_stage else "-"
        return (
            f"stage: {stage_name} | tokens: {self._tokens_in}/{self._tokens_out} | "
            f"cost: ${self._cost_usd:.2f} | turns: {self._turns} | "
            f"elapsed: {elapsed // 60}:{elapsed % 60:02d} | session: {self.session_id}"
        )

    def _render(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="events", ratio=4),
            Layout(name="status", size=3),
        )
        layout["events"].update(
            Panel(Text("\n".join(self.recent_events)), title="Progress")
        )
        layout["status"].update(Panel(Text(self.render_status_bar())))
        return layout
```

- [ ] **Step 4: Run — expect PASS**

Run: `make test TEST=tests/adapters/test_progress_console.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/a2sdlc/adapters/progress_console.py tests/adapters/test_progress_console.py
git commit -m "feat(adapters): add ConsoleProgressAdapter with rich.Live layout"
```

---

## Task 5: `local_branch_git` adapter (no-origin overrides)

**Files:**
- Create: `src/a2sdlc/adapters/local_branch_git.py`
- Create: `tests/adapters/test_local_branch_git.py`

**What changes:** Existing `LocalGitAdapter` in `adapters/git.py:47-54` calls `git fetch origin` unconditionally in `setup_branch` and `sync_with_base`. The local-mode adapter subclasses it and overrides those two methods to skip remote interaction.

- [ ] **Step 1: Write failing test using a temp git repo**

Create `tests/adapters/test_local_branch_git.py`:

```python
"""Behavior tests for local_branch git adapter."""

import subprocess
from pathlib import Path

import pytest

from a2sdlc.adapters.local_branch_git import LocalBranchGitAdapter


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "README.md").write_text("init")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


def test_setup_branch_creates_branch_without_touching_origin(tmp_path):
    """GIVEN a repo with no `origin` remote
    WHEN setup_branch is called
    THEN the branch is created locally without error."""
    _init_repo(tmp_path)
    adapter = LocalBranchGitAdapter(project_root=tmp_path)

    adapter.setup_branch("a2sdlc/test-session", "main")

    current = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert current == "a2sdlc/test-session"


def test_setup_branch_reuses_existing_branch(tmp_path):
    """GIVEN a session branch already exists
    WHEN setup_branch is called again
    THEN it checks out the existing branch (no -b)."""
    _init_repo(tmp_path)
    adapter = LocalBranchGitAdapter(project_root=tmp_path)
    adapter.setup_branch("a2sdlc/sid1", "main")
    # Switch away
    subprocess.run(["git", "checkout", "main"], cwd=tmp_path, check=True)
    # Re-setup same branch
    adapter.setup_branch("a2sdlc/sid1", "main")
    current = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert current == "a2sdlc/sid1"


def test_push_is_noop(tmp_path):
    """GIVEN a local branch
    WHEN push() is called
    THEN no error is raised and no network IO occurs."""
    _init_repo(tmp_path)
    adapter = LocalBranchGitAdapter(project_root=tmp_path)
    adapter.setup_branch("a2sdlc/test", "main")
    adapter.push()  # must not raise


def test_sync_with_base_is_noop(tmp_path):
    """GIVEN a local branch
    WHEN sync_with_base is called
    THEN it returns True and does not touch origin."""
    _init_repo(tmp_path)
    adapter = LocalBranchGitAdapter(project_root=tmp_path)
    adapter.setup_branch("a2sdlc/test", "main")
    assert adapter.sync_with_base("main") is True
```

- [ ] **Step 2: Run — expect ImportError**

Run: `make test TEST=tests/adapters/test_local_branch_git.py`
Expected: FAIL.

- [ ] **Step 3: Implement the adapter**

Create `src/a2sdlc/adapters/local_branch_git.py`:

```python
"""Local-only git adapter: branches stay on the laptop, no origin interaction."""

from __future__ import annotations

import subprocess
from pathlib import Path

from a2sdlc.adapters.git import LocalGitAdapter
from a2sdlc.domain.exceptions import BlockedError


class LocalBranchGitAdapter(LocalGitAdapter):
    """GitAdapter for fully-offline use. Inherits state read/write from LocalGitAdapter."""

    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root=project_root)

    def setup_branch(self, branch_name: str, base: str) -> str:
        """Create or check out branch_name without fetching origin."""
        # Does the branch already exist?
        ls = subprocess.run(
            ["git", "rev-parse", "--verify", branch_name],
            cwd=self._project_root, capture_output=True, text=True,
        )
        if ls.returncode == 0:
            result = subprocess.run(
                ["git", "checkout", branch_name],
                cwd=self._project_root, capture_output=True, text=True,
            )
        else:
            result = subprocess.run(
                ["git", "checkout", "-b", branch_name, base],
                cwd=self._project_root, capture_output=True, text=True,
            )
        if result.returncode != 0:
            raise BlockedError(f"git checkout failed: {result.stderr.strip()}")
        return branch_name

    def sync_with_base(self, base: str) -> bool:
        """No-op locally — there is no origin to sync with."""
        return True

    def push(self) -> None:
        """No-op — local-only adapter."""
        return None
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `make test TEST=tests/adapters/test_local_branch_git.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/a2sdlc/adapters/local_branch_git.py tests/adapters/test_local_branch_git.py
git commit -m "feat(adapters): add LocalBranchGitAdapter (no origin fetch/push)"
```

---

## Task 6: `local_noop_review` adapter — full `ReviewAdapter` with file-backed PR

**Files:**
- Create: `src/a2sdlc/adapters/local_noop_review.py`
- Create: `tests/adapters/test_local_noop_review.py`

**What changes:** Implements the full `ReviewAdapter` protocol (10 methods, see `adapters/review.py:29-47`) with all state backed by `.a2sdlc/pr.json` and `.a2sdlc/feedback.json` on the session branch. This is what makes SPEC's `create_draft_pr` and MERGE's `get_approvals` work locally.

- [ ] **Step 1: Write failing tests for `create_draft_pr` and `pr.json`**

Create `tests/adapters/test_local_noop_review.py`:

```python
"""Behavior tests for local_noop_review adapter."""

import json
from pathlib import Path

from a2sdlc.adapters.local_noop_review import LocalNoopReviewAdapter
from a2sdlc.adapters.review import Approval


def test_create_draft_pr_writes_pr_json(tmp_path):
    """GIVEN a fresh project root
    WHEN create_draft_pr is called
    THEN .a2sdlc/pr.json exists with pr_number=1 and status=draft."""
    (tmp_path / ".a2sdlc").mkdir()
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)

    pr_number = adapter.create_draft_pr(
        branch="a2sdlc/sid", base="main", title="title", ticket_key="sid"
    )

    assert pr_number == 1
    data = json.loads((tmp_path / ".a2sdlc" / "pr.json").read_text())
    assert data["pr_number"] == 1
    assert data["status"] == "draft"
    assert data["title"] == "title"


def test_get_approvals_returns_local_non_bot(tmp_path):
    """GIVEN a draft PR
    WHEN get_approvals is called
    THEN returns [Approval(user='local', is_bot=False)]."""
    (tmp_path / ".a2sdlc").mkdir()
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")

    approvals = adapter.get_approvals(1)
    assert approvals == [Approval(user="local", is_bot=False)]


def test_post_review_changes_requested_writes_feedback(tmp_path):
    """GIVEN a draft PR
    WHEN post_review is called with verdict=changes_requested
    THEN feedback.json is written with consumed=false."""
    (tmp_path / ".a2sdlc").mkdir()
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")

    adapter.post_review(1, body="Needs work", verdict="changes_requested")

    fb = json.loads((tmp_path / ".a2sdlc" / "feedback.json").read_text())
    assert fb["consumed"] is False
    assert "Needs work" in fb["body"]


def test_post_review_approved_does_not_write_feedback(tmp_path):
    """GIVEN a draft PR
    WHEN post_review is called with verdict=approved
    THEN feedback.json is NOT written."""
    (tmp_path / ".a2sdlc").mkdir()
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")

    adapter.post_review(1, body="LGTM", verdict="approved")

    assert not (tmp_path / ".a2sdlc" / "feedback.json").exists()


def test_collect_pr_feedback_filters_by_since(tmp_path):
    """GIVEN feedback with created_at=T1
    AND since=T2 where T2 > T1
    WHEN collect_pr_feedback is called
    THEN empty list is returned."""
    from datetime import datetime, timedelta, timezone

    (tmp_path / ".a2sdlc").mkdir()
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    adapter.post_review(1, "fix this", "changes_requested")

    since = datetime.now(timezone.utc) + timedelta(hours=1)
    assert adapter.collect_pr_feedback(1, since) == []


def test_collect_pr_feedback_does_not_consume(tmp_path):
    """GIVEN unconsumed feedback
    WHEN collect_pr_feedback is called
    THEN feedback.json consumed flag stays False (adapter is read-only)."""
    from datetime import datetime, timezone

    (tmp_path / ".a2sdlc").mkdir()
    adapter = LocalNoopReviewAdapter(project_root=tmp_path)
    adapter.create_draft_pr("a2sdlc/sid", "main", "t", "sid")
    adapter.post_review(1, "fix", "changes_requested")

    adapter.collect_pr_feedback(1, datetime.min.replace(tzinfo=timezone.utc))

    fb = json.loads((tmp_path / ".a2sdlc" / "feedback.json").read_text())
    assert fb["consumed"] is False
```

- [ ] **Step 2: Run — expect ImportError**

Run: `make test TEST=tests/adapters/test_local_noop_review.py`
Expected: FAIL.

- [ ] **Step 3: Implement `local_noop_review.py`**

Create `src/a2sdlc/adapters/local_noop_review.py`:

```python
"""Local no-op review adapter — file-backed PR mock for offline pipeline runs."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from a2sdlc.adapters.review import Approval, ReviewComment
from a2sdlc.domain.handover import FeedbackItem, HandoverComment


class LocalNoopReviewAdapter:
    """Implements ReviewAdapter with all PR state backed by files."""

    def __init__(self, project_root: Path) -> None:
        self._root = project_root

    @property
    def _pr_path(self) -> Path:
        return self._root / ".a2sdlc" / "pr.json"

    @property
    def _feedback_path(self) -> Path:
        return self._root / ".a2sdlc" / "feedback.json"

    def _read_pr(self) -> dict:
        return json.loads(self._pr_path.read_text())

    def _write_pr(self, data: dict) -> None:
        self._pr_path.write_text(json.dumps(data, indent=2))

    def create_draft_pr(
        self, branch: str, base: str, title: str, ticket_key: str
    ) -> int:
        data = {
            "pr_number": 1,
            "branch": branch,
            "base": base,
            "ticket_key": ticket_key,
            "status": "draft",
            "title": title,
            "body": "",
            "reviews": [],
        }
        self._write_pr(data)
        return 1

    def update_pr(self, pr_number: int, title: str, body: str, ticket_key: str) -> None:
        data = self._read_pr()
        data["title"] = title
        data["body"] = body
        self._write_pr(data)

    def mark_pr_ready(self, pr_number: int) -> None:
        data = self._read_pr()
        data["status"] = "ready"
        self._write_pr(data)

    def merge_pr(self, pr_number: int, method: str = "squash") -> None:
        data = self._read_pr()
        data["status"] = "merged"
        self._write_pr(data)

    def get_approvals(self, pr_number: int) -> list[Approval]:
        return [Approval(user="local", is_bot=False)]

    def post_review(self, pr_number: int, body: str, verdict: str) -> None:
        data = self._read_pr()
        now = datetime.now(timezone.utc).isoformat()
        cycle = len(data["reviews"]) + 1
        data["reviews"].append(
            {"cycle": cycle, "verdict": verdict, "body": body, "created_at": now}
        )
        self._write_pr(data)

        if verdict == "changes_requested":
            self._feedback_path.write_text(
                json.dumps(
                    {
                        "consumed": False,
                        "body": body,
                        "cycle": cycle,
                        "created_at": now,
                    },
                    indent=2,
                )
            )

    def read_pr_diff(self, pr_number: int) -> str:
        data = self._read_pr()
        base = data.get("base", "main")
        result = subprocess.run(
            ["git", "diff", f"{base}..HEAD"],
            cwd=self._root, capture_output=True, text=True,
        )
        return result.stdout

    def read_pr_comments(self, pr_number: int) -> list[ReviewComment]:
        data = self._read_pr()
        return [
            ReviewComment(
                author="local",
                body=r["body"],
                created_at=r["created_at"],
            )
            for r in data.get("reviews", [])
        ]

    def collect_pr_feedback(
        self, pr_number: int, since: datetime
    ) -> list[FeedbackItem]:
        if not self._feedback_path.exists():
            return []
        fb = json.loads(self._feedback_path.read_text())
        if fb.get("consumed"):
            return []
        created = datetime.fromisoformat(fb["created_at"])
        if created <= since:
            return []
        return [
            FeedbackItem(
                author="local",
                body=fb["body"],
                created_at=created,
                stage=None,
            )
        ]

    def find_last_handover(self, pr_number: int) -> HandoverComment | None:
        # All handover lives on the issue (work-adapter) side locally.
        return None

    # Runner-only helper — not part of the ReviewAdapter protocol.
    def mark_feedback_consumed(self) -> None:
        if not self._feedback_path.exists():
            return
        fb = json.loads(self._feedback_path.read_text())
        fb["consumed"] = True
        self._feedback_path.write_text(json.dumps(fb, indent=2))
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `make test TEST=tests/adapters/test_local_noop_review.py`
Expected: PASS.

- [ ] **Step 5: Run lint to catch protocol mismatches**

Run: `make lint`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/a2sdlc/adapters/local_noop_review.py tests/adapters/test_local_noop_review.py
git commit -m "feat(adapters): add LocalNoopReviewAdapter (file-backed PR mock)"
```

---

## Task 7: `local_file_work` adapter — full `WorkAdapter`

**Files:**
- Create: `src/a2sdlc/adapters/local_file_work.py`
- Create: `tests/adapters/test_local_file_work.py`

**What changes:** Implements the full `WorkAdapter` protocol (12 methods per `adapters/work.py:28-45`). Reads ticket from file, persists to `.a2sdlc/ticket.md`, stores handover as `.a2sdlc/handover/<stage>.md`, routes feedback presence into `is_feedback` on `parse_event`.

- [ ] **Step 1: Write behavior tests**

Create `tests/adapters/test_local_file_work.py`:

```python
"""Behavior tests for local_file work adapter."""

import json
from datetime import datetime, timezone
from pathlib import Path

from a2sdlc.adapters.local_file_work import LocalFileWorkAdapter
from a2sdlc.domain.models import StageName


def test_parse_event_spec_first_run(tmp_path):
    """GIVEN session_id, stage=SPEC, no feedback.json
    WHEN parse_event is called
    THEN PipelineEvent has trigger_stage=SPEC, is_feedback=False, pr_number=None."""
    (tmp_path / ".a2sdlc").mkdir()
    adapter = LocalFileWorkAdapter(
        project_root=tmp_path, session_id="sid1", stage=StageName.SPEC,
        ticket_path=None,
    )
    event = adapter.parse_event()
    assert event.key == "sid1"
    assert event.trigger_stage == StageName.SPEC
    assert event.is_feedback is False
    assert event.pr_number is None


def test_parse_event_implement_with_pr(tmp_path):
    """GIVEN pr.json exists with pr_number=1
    WHEN parse_event is called for IMPLEMENT
    THEN event.pr_number is 1."""
    (tmp_path / ".a2sdlc").mkdir()
    (tmp_path / ".a2sdlc" / "pr.json").write_text(
        json.dumps({"pr_number": 1, "status": "draft"})
    )
    adapter = LocalFileWorkAdapter(
        project_root=tmp_path, session_id="sid", stage=StageName.IMPLEMENT,
        ticket_path=None,
    )
    event = adapter.parse_event()
    assert event.pr_number == 1


def test_parse_event_unconsumed_feedback_flips_is_feedback(tmp_path):
    """GIVEN feedback.json exists with consumed=false
    WHEN parse_event is called for IMPLEMENT
    THEN event.is_feedback is True AND event.trigger_stage is None."""
    (tmp_path / ".a2sdlc").mkdir()
    now = datetime.now(timezone.utc).isoformat()
    (tmp_path / ".a2sdlc" / "pr.json").write_text(json.dumps({"pr_number": 1}))
    (tmp_path / ".a2sdlc" / "feedback.json").write_text(
        json.dumps({"consumed": False, "body": "fix", "cycle": 1, "created_at": now})
    )
    adapter = LocalFileWorkAdapter(
        project_root=tmp_path, session_id="sid", stage=StageName.IMPLEMENT,
        ticket_path=None,
    )
    event = adapter.parse_event()
    assert event.is_feedback is True
    assert event.trigger_stage is None


def test_get_ticket_reads_persisted_file(tmp_path):
    """GIVEN .a2sdlc/ticket.md exists
    WHEN get_ticket is called
    THEN its content is returned."""
    (tmp_path / ".a2sdlc").mkdir()
    (tmp_path / ".a2sdlc" / "ticket.md").write_text("Feature X\n\nDo thing.")
    adapter = LocalFileWorkAdapter(
        project_root=tmp_path, session_id="sid", stage=StageName.SPEC,
        ticket_path=None,
    )
    assert adapter.get_ticket("sid") == "Feature X\n\nDo thing."


def test_format_branch_matches_spec(tmp_path):
    """GIVEN ticket_key='abc123'
    WHEN format_branch is called
    THEN returns 'a2sdlc/abc123'."""
    adapter = LocalFileWorkAdapter(
        project_root=tmp_path, session_id="abc123", stage=StageName.SPEC,
        ticket_path=None,
    )
    assert adapter.format_branch("abc123") == "a2sdlc/abc123"


def test_begin_and_finalize_comment_writes_handover_file(tmp_path):
    """GIVEN an active stage=SPEC
    WHEN begin_comment then finalize_comment(id, body) are called
    THEN .a2sdlc/handover/spec.md contains body."""
    (tmp_path / ".a2sdlc").mkdir()
    adapter = LocalFileWorkAdapter(
        project_root=tmp_path, session_id="sid", stage=StageName.SPEC,
        ticket_path=None,
    )
    cid = adapter.begin_comment("sid")
    adapter.finalize_comment(cid, "## Spec\n\nDetails.")

    handover = (tmp_path / ".a2sdlc" / "handover" / "spec.md").read_text()
    assert "## Spec" in handover


def test_find_last_handover_returns_newest(tmp_path):
    """GIVEN handover/spec.md and handover/implement.md (implement newer)
    WHEN find_last_handover is called
    THEN returns HandoverComment for implement stage."""
    import time

    (tmp_path / ".a2sdlc" / "handover").mkdir(parents=True)
    (tmp_path / ".a2sdlc" / "handover" / "spec.md").write_text("spec body")
    time.sleep(0.01)
    (tmp_path / ".a2sdlc" / "handover" / "implement.md").write_text("impl body")

    adapter = LocalFileWorkAdapter(
        project_root=tmp_path, session_id="sid", stage=StageName.REVIEW,
        ticket_path=None,
    )
    handover = adapter.find_last_handover("sid")
    assert handover is not None
    assert handover.stage == StageName.IMPLEMENT
    assert "impl body" in handover.body


def test_ticket_path_copies_to_a2sdlc_on_first_call(tmp_path):
    """GIVEN a ticket file outside the repo
    WHEN the adapter is constructed with ticket_path
    THEN .a2sdlc/ticket.md is created with that content."""
    ticket = tmp_path / "my-ticket.md"
    ticket.write_text("TICKET CONTENT")
    (tmp_path / ".a2sdlc").mkdir()

    LocalFileWorkAdapter(
        project_root=tmp_path, session_id="sid", stage=StageName.SPEC,
        ticket_path=ticket,
    )
    assert (tmp_path / ".a2sdlc" / "ticket.md").read_text() == "TICKET CONTENT"
```

- [ ] **Step 2: Run — expect ImportError**

Run: `make test TEST=tests/adapters/test_local_file_work.py`
Expected: FAIL.

- [ ] **Step 3: Implement `local_file_work.py`**

Create `src/a2sdlc/adapters/local_file_work.py`:

```python
"""Local file-backed WorkAdapter for offline pipeline runs."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from a2sdlc.adapters.work import PipelineEvent
from a2sdlc.domain.handover import FeedbackItem, HandoverComment
from a2sdlc.domain.models import StageName

_log = logging.getLogger(__name__)


class LocalFileWorkAdapter:
    """Full WorkAdapter implementation backed by files in .a2sdlc/."""

    def __init__(
        self,
        project_root: Path,
        session_id: str,
        stage: StageName,
        ticket_path: Path | None,
    ) -> None:
        self._root = project_root
        self._session_id = session_id
        self._stage = stage
        self._a2sdlc = project_root / ".a2sdlc"
        self._a2sdlc.mkdir(exist_ok=True)
        (self._a2sdlc / "handover").mkdir(exist_ok=True)

        if ticket_path is not None:
            (self._a2sdlc / "ticket.md").write_text(ticket_path.read_text())

        # Maps comment_id -> active stage for finalize_comment routing.
        self._comment_stage: dict[str, StageName] = {}
        self._comment_counter = 0

    # ── WorkAdapter protocol ──

    def parse_event(self) -> PipelineEvent:
        pr_number = self._read_pr_number()
        is_feedback = self._feedback_is_pending()
        trigger_stage = None if is_feedback else self._stage
        return PipelineEvent(
            key=self._session_id,
            trigger_stage=trigger_stage,
            is_feedback=is_feedback,
            pr_number=pr_number,
        )

    def get_ticket(self, key: str) -> str:
        ticket_file = self._a2sdlc / "ticket.md"
        return ticket_file.read_text() if ticket_file.exists() else ""

    def get_labels(self, key: str) -> list[str]:
        return []

    def begin_comment(self, key: str) -> str:
        self._comment_counter += 1
        cid = f"{key}-{self._stage.value}-{self._comment_counter}"
        self._comment_stage[cid] = self._stage
        return cid

    def update_progress(self, comment_id: str, body: str) -> None:
        # Live progress goes to the ProgressAdapter; nothing to persist here.
        return None

    def finalize_comment(self, comment_id: str, body: str) -> None:
        stage = self._comment_stage.get(comment_id, self._stage)
        target = self._a2sdlc / "handover" / f"{stage.value}.md"
        target.write_text(body)

    def set_stage_label(self, key: str, stage: StageName) -> None:
        _log.info("set_stage_label (noop locally)", extra={"stage": stage.value})

    def set_done_label(self, key: str) -> None:
        _log.info("set_done_label (noop locally)")

    def set_blocked(self, key: str, reason: str) -> None:
        _log.info("set_blocked (noop locally)", extra={"reason": reason})

    def format_branch(self, ticket_key: str) -> str:
        return f"a2sdlc/{ticket_key}"

    def collect_issue_feedback(
        self, key: str, since: datetime
    ) -> list[FeedbackItem]:
        return []

    def find_last_handover(self, key: str) -> HandoverComment | None:
        handover_dir = self._a2sdlc / "handover"
        if not handover_dir.is_dir():
            return None
        files = list(handover_dir.glob("*.md"))
        if not files:
            return None
        newest = max(files, key=lambda p: p.stat().st_mtime)
        stage_name = newest.stem
        try:
            stage = StageName(stage_name)
        except ValueError:
            return None
        return HandoverComment(
            stage=stage,
            body=newest.read_text(),
            created_at=datetime.fromtimestamp(
                newest.stat().st_mtime, tz=timezone.utc
            ),
        )

    # ── Internal helpers ──

    def _read_pr_number(self) -> int | None:
        pr_path = self._a2sdlc / "pr.json"
        if not pr_path.exists():
            return None
        try:
            return int(json.loads(pr_path.read_text()).get("pr_number"))
        except (json.JSONDecodeError, TypeError):
            return None

    def _feedback_is_pending(self) -> bool:
        fb_path = self._a2sdlc / "feedback.json"
        if not fb_path.exists():
            return False
        try:
            return not json.loads(fb_path.read_text()).get("consumed", True)
        except json.JSONDecodeError:
            return False
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `make test TEST=tests/adapters/test_local_file_work.py`
Expected: PASS.

- [ ] **Step 5: Verify protocol conformance with lint**

Run: `make lint`
Expected: PASS (import-linter and ty should both be happy).

- [ ] **Step 6: Commit**

```bash
git add src/a2sdlc/adapters/local_file_work.py tests/adapters/test_local_file_work.py
git commit -m "feat(adapters): add LocalFileWorkAdapter (file-backed WorkAdapter)"
```

---

## Task 8: Adapter factory

**Files:**
- Modify: `src/a2sdlc/config.py` (or create `src/a2sdlc/adapters/factory.py` if config grows)
- Create: `tests/adapters/test_factory.py`

**What changes:** Given an `AdaptersConfig`, return concrete adapter instances. Keeps adapter selection out of `pipeline/dispatch.py`.

- [ ] **Step 1: Write failing test**

Create `tests/adapters/test_factory.py`:

```python
"""Adapter factory selects concrete implementations by name."""

from pathlib import Path

from a2sdlc.adapters.factory import build_work_adapter, build_review_adapter, \
    build_git_adapter, build_progress_adapter
from a2sdlc.adapters.local_file_work import LocalFileWorkAdapter
from a2sdlc.adapters.local_noop_review import LocalNoopReviewAdapter
from a2sdlc.adapters.local_branch_git import LocalBranchGitAdapter
from a2sdlc.adapters.progress_console import ConsoleProgressAdapter
from a2sdlc.adapters.progress_gh_actions import GhActionsProgressAdapter
from a2sdlc.domain.models import StageName


def test_build_work_adapter_local_file(tmp_path):
    (tmp_path / ".a2sdlc").mkdir()
    w = build_work_adapter("local_file", project_root=tmp_path,
                            session_id="sid", stage=StageName.SPEC, ticket_path=None)
    assert isinstance(w, LocalFileWorkAdapter)


def test_build_review_adapter_local_noop(tmp_path):
    r = build_review_adapter("local_noop", project_root=tmp_path)
    assert isinstance(r, LocalNoopReviewAdapter)


def test_build_git_adapter_local_branch(tmp_path):
    g = build_git_adapter("local_branch", project_root=tmp_path)
    assert isinstance(g, LocalBranchGitAdapter)


def test_build_progress_adapter_console():
    p = build_progress_adapter("console")
    assert isinstance(p, ConsoleProgressAdapter)


def test_build_progress_adapter_gh_actions():
    p = build_progress_adapter("gh_actions")
    assert isinstance(p, GhActionsProgressAdapter)


def test_build_work_adapter_unknown_raises():
    import pytest
    with pytest.raises(ValueError, match="unknown work adapter"):
        build_work_adapter("nonsense", project_root=Path("."),
                           session_id="s", stage=StageName.SPEC, ticket_path=None)
```

- [ ] **Step 2: Run — expect ImportError**

Run: `make test TEST=tests/adapters/test_factory.py`
Expected: FAIL.

- [ ] **Step 3: Implement `adapters/factory.py`**

Create `src/a2sdlc/adapters/factory.py`:

```python
"""Adapter factory — maps config names to concrete implementations."""

from __future__ import annotations

from pathlib import Path

from a2sdlc.adapters.local_branch_git import LocalBranchGitAdapter
from a2sdlc.adapters.local_file_work import LocalFileWorkAdapter
from a2sdlc.adapters.local_noop_review import LocalNoopReviewAdapter
from a2sdlc.adapters.progress_console import ConsoleProgressAdapter
from a2sdlc.adapters.progress_gh_actions import GhActionsProgressAdapter
from a2sdlc.domain.models import StageName


def build_work_adapter(
    name: str,
    *,
    project_root: Path,
    session_id: str,
    stage: StageName,
    ticket_path: Path | None,
):
    if name == "local_file":
        return LocalFileWorkAdapter(
            project_root=project_root,
            session_id=session_id,
            stage=stage,
            ticket_path=ticket_path,
        )
    if name == "jira":
        # Lazy import to avoid PyGithub/jira pulls when not needed
        from a2sdlc.adapters.work import make_jira_work_adapter  # type: ignore[attr-defined]
        return make_jira_work_adapter(project_root=project_root)
    raise ValueError(f"unknown work adapter: {name}")


def build_review_adapter(name: str, *, project_root: Path):
    if name == "local_noop":
        return LocalNoopReviewAdapter(project_root=project_root)
    if name == "github":
        from a2sdlc.adapters.github import make_github_review_adapter  # type: ignore[attr-defined]
        return make_github_review_adapter(project_root=project_root)
    raise ValueError(f"unknown review adapter: {name}")


def build_git_adapter(name: str, *, project_root: Path):
    if name == "local_branch":
        return LocalBranchGitAdapter(project_root=project_root)
    if name == "github":
        from a2sdlc.adapters.git import LocalGitAdapter
        return LocalGitAdapter(project_root=project_root)
    raise ValueError(f"unknown git adapter: {name}")


def build_progress_adapter(name: str):
    if name == "console":
        return ConsoleProgressAdapter()
    if name == "gh_actions":
        return GhActionsProgressAdapter()
    raise ValueError(f"unknown progress adapter: {name}")
```

> **Note:** If `make_jira_work_adapter` or `make_github_review_adapter` do not exist in the current code, the factory's branches for `"jira"` and `"github"` need to call the actual constructor names (see `src/a2sdlc/adapters/work.py` and `adapters/github.py`). Verify when implementing — the task is to make the factory shape correct, not to refactor CI-side adapters.

- [ ] **Step 4: Run tests — expect PASS**

Run: `make test TEST=tests/adapters/test_factory.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/a2sdlc/adapters/factory.py tests/adapters/test_factory.py
git commit -m "feat(adapters): add adapter factory for config-driven selection"
```

---

## Task 9: Wire `ProgressAdapter` into `pipeline/runner.py` and `pipeline/dispatch.py`

**Files:**
- Modify: `src/a2sdlc/pipeline/runner.py`
- Modify: `src/a2sdlc/pipeline/dispatch.py`
- Modify: `src/a2sdlc/pipeline/context.py` (DispatchContext likely here)
- Modify: `tests/fakes.py` (add `FakeProgressAdapter`)
- Modify: relevant dispatch tests

**What changes:** Replace hardcoded `print("::group::...")` in `runner.py:228-233` and `dispatch.py:255-257` with calls on `ctx.progress`. Add `progress: ProgressAdapter` to `DispatchContext`. Existing tests that check capsys output update to check `FakeProgressAdapter.events` instead.

- [ ] **Step 1: Add `FakeProgressAdapter` to `tests/fakes.py`**

Append to `tests/fakes.py`:

```python
# ── FakeProgressAdapter ───────────────────────────────────────────────

class FakeProgressAdapter:
    """Records all calls for assertions."""

    def __init__(self) -> None:
        self.started: list[tuple[str, str]] = []
        self.events: list[tuple[str, str]] = []
        self.ended: list[tuple[str, bool]] = []
        self.groups_open: list[str] = []
        self.groups_closed: int = 0

    def on_stage_start(self, stage, session_id: str) -> None:
        self.started.append((stage.value, session_id))

    def on_event(self, event_type: str, text: str) -> None:
        self.events.append((event_type, text))

    def on_stage_end(self, stage, success: bool) -> None:
        self.ended.append((stage.value, success))

    def on_group_open(self, title: str) -> None:
        self.groups_open.append(title)

    def on_group_close(self) -> None:
        self.groups_closed += 1
```

- [ ] **Step 2: Write failing test — dispatch should call progress adapter on group open/close**

Add to `tests/pipeline/test_dispatch.py` (or create):

```python
def test_dispatch_emits_progress_group_around_agent_output(
    fake_ctx_with_progress,  # fixture that builds DispatchContext with FakeProgressAdapter
):
    """GIVEN a successful stage run
    WHEN dispatch completes
    THEN progress.on_group_open/on_group_close were called once each."""
    # setup a run that reaches the "log full output" block
    ...
    assert len(fake_ctx_with_progress.progress.groups_open) == 1
    assert fake_ctx_with_progress.progress.groups_closed == 1
```

(If no suitable fixture exists, write a minimal one inline — details depend on existing test scaffolding. Keep scope small.)

- [ ] **Step 3: Run — expect FAIL (engine still uses `print`)**

Run: `make test TEST=tests/pipeline/test_dispatch.py`
Expected: FAIL.

- [ ] **Step 4: Add `progress: ProgressAdapter` to `DispatchContext`**

Edit `src/a2sdlc/pipeline/context.py` (or wherever `DispatchContext` lives — search with Grep):

```python
from a2sdlc.adapters.protocols import ProgressAdapter

@dataclass
class DispatchContext:
    # ...existing fields...
    progress: ProgressAdapter
```

- [ ] **Step 5: Replace hardcoded prints in `dispatch.py`**

Edit `src/a2sdlc/pipeline/dispatch.py` around line 255:

```python
# 12. Log full output via progress adapter
ctx.progress.on_group_open(f"Agent output ({len(exec_result.output)} chars)")
ctx.progress.on_event("output", exec_result.output)
ctx.progress.on_group_close()
```

Similarly replace the `print(f"::group::...")` block in `pipeline/runner.py` around line 228 with `self._progress.on_event(...)` calls. Add `progress: ProgressAdapter` to `ClaudeSDKRunner.__init__` (the class in `runner.py`).

- [ ] **Step 6: Update all call sites that construct `DispatchContext` and `ClaudeSDKRunner`**

Find with Grep:

```bash
```

Use Grep for `DispatchContext(` and `ClaudeSDKRunner(` and pass `progress=...` everywhere (tests and CLI). For CI-side callers that haven't been wired yet, pass `GhActionsProgressAdapter()`.

- [ ] **Step 7: Run all tests**

Run: `make test`
Expected: green (may require fixing a few existing tests to accept the new argument).

- [ ] **Step 8: Commit**

```bash
git add src/a2sdlc/pipeline/ tests/
git commit -m "refactor(pipeline): route progress via ProgressAdapter (remove hardcoded prints)"
```

---

## Task 10: CLI — `run-stage` subcommand

**Files:**
- Create: `src/a2sdlc/cli_local.py`
- Modify: `src/a2sdlc/cli.py`
- Create: `tests/test_cli_local.py`

**What changes:** Adds `a2sdlc run-stage <stage> --session <sid> [--ticket <file>] <repo>` subcommand. Session id inferred from branch name if `--session` omitted. Wires adapters via the factory, builds `DispatchContext`, calls `dispatch()`, flips feedback consumption on success, prints post-run output.

- [ ] **Step 1: Write a failing CLI smoke test**

Create `tests/test_cli_local.py`:

```python
"""CLI smoke tests for run-stage."""

import subprocess
from pathlib import Path


def _init_minimal_repo(tmp_path: Path, ticket_body: str) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / ".a2sdlc").mkdir()
    (tmp_path / ".a2sdlc" / "config.yaml").write_text(
        "adapters:\n"
        "  work: local_file\n  review: local_noop\n"
        "  git: local_branch\n  progress: console\n"
        "stages: [spec, implement, review, merge]\n"
        "spec:\n  mode: auto\n"
        "quality:\n  check_command: 'true'\n"
        "model: claude-sonnet-4-6\n"
    )
    ticket = tmp_path / "ticket.md"
    ticket.write_text(ticket_body)
    (tmp_path / "README.md").write_text("init")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    return ticket


def test_run_stage_creates_session_branch(tmp_path, monkeypatch):
    """GIVEN a minimal repo with .a2sdlc/config.yaml and a ticket file
    WHEN `a2sdlc run-stage spec --ticket ticket.md .` runs
    THEN an a2sdlc/<sid> branch exists AND .a2sdlc/ticket.md is persisted.

    We mock the StageRunner to avoid hitting Claude; see conftest.
    """
    ticket = _init_minimal_repo(tmp_path, "Build feature X")

    # Inject fake runner via env var or fixture — implementation detail.
    # For this test we assert the side effects that do NOT depend on LLM output.
    from a2sdlc.cli_local import run_stage_entry

    exit_code = run_stage_entry(
        argv=["spec", "--session", "testsid", "--ticket", str(ticket), str(tmp_path)],
        runner_override="fake",  # test hook
    )
    assert exit_code == 0

    # Branch exists
    branch_exists = subprocess.run(
        ["git", "rev-parse", "--verify", "a2sdlc/testsid"],
        cwd=tmp_path, capture_output=True,
    ).returncode == 0
    assert branch_exists
    # Ticket copied
    assert (tmp_path / ".a2sdlc" / "ticket.md").read_text() == "Build feature X"


def test_run_stage_infers_session_id_from_branch(tmp_path):
    """GIVEN we are checked out on a2sdlc/fromBranch
    WHEN run-stage implement is invoked without --session
    THEN the runner operates on session_id='fromBranch'."""
    # setup + assert ... (write based on run_stage_entry's parsing)
    ...
```

- [ ] **Step 2: Run — expect ImportError**

Run: `make test TEST=tests/test_cli_local.py`
Expected: FAIL.

- [ ] **Step 3: Implement `src/a2sdlc/cli_local.py`**

```python
"""Local runner CLI — a2sdlc run-stage subcommand."""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import time
from pathlib import Path

from ulid import ULID  # see pyproject: we need python-ulid (add in this task)

from a2sdlc.adapters.factory import (
    build_git_adapter, build_progress_adapter,
    build_review_adapter, build_work_adapter,
)
from a2sdlc.adapters.local_noop_review import LocalNoopReviewAdapter
from a2sdlc.config import load_config_file
from a2sdlc.domain.models import StageName
from a2sdlc.pipeline.context import DispatchContext
from a2sdlc.pipeline.dispatch import dispatch
from a2sdlc.pipeline.runner import ClaudeSDKRunner


def _infer_session_id(project_root: Path) -> str | None:
    res = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=project_root, capture_output=True, text=True,
    )
    if res.returncode != 0:
        return None
    branch = res.stdout.strip()
    if branch.startswith("a2sdlc/"):
        return branch.removeprefix("a2sdlc/")
    return None


def run_stage_entry(argv: list[str], runner_override: str | None = None) -> int:
    parser = argparse.ArgumentParser(prog="a2sdlc run-stage")
    parser.add_argument("stage", choices=[s.value for s in StageName])
    parser.add_argument("--session", default=None)
    parser.add_argument("--ticket", default=None, type=Path)
    parser.add_argument("--no-track", action="store_true")
    parser.add_argument("repo", type=Path)
    args = parser.parse_args(argv)

    project_root = args.repo.resolve()
    stage = StageName(args.stage)

    session_id = args.session or _infer_session_id(project_root) or str(ULID())

    cfg = load_config_file(project_root)

    # Ticket is required on SPEC first run
    if stage == StageName.SPEC and args.ticket is None:
        existing = project_root / ".a2sdlc" / "ticket.md"
        if not existing.exists():
            print("error: --ticket is required on first SPEC invocation", file=sys.stderr)
            return 2

    # Build adapters
    work = build_work_adapter(
        cfg.adapters.work,
        project_root=project_root,
        session_id=session_id,
        stage=stage,
        ticket_path=args.ticket,
    )
    review = build_review_adapter(cfg.adapters.review, project_root=project_root)
    git = build_git_adapter(cfg.adapters.git, project_root=project_root)
    progress = build_progress_adapter(cfg.adapters.progress)

    # Build runner (injected override for tests)
    if runner_override == "fake":
        from tests.fakes import FakeStageRunner
        runner = FakeStageRunner()
    else:
        runner = ClaudeSDKRunner(progress=progress)

    ctx = DispatchContext(
        work=work, review=review, git=git,
        runner=runner, progress=progress,
        project_root=project_root,
        config=cfg,
        run_id=None,          # no idempotency self-trigger
        logger=__import__("logging").getLogger("a2sdlc.local"),
    )

    start = time.monotonic()
    result = asyncio.run(dispatch(ctx))
    elapsed = time.monotonic() - start

    # Mark feedback consumed on successful dispatch
    if isinstance(review, LocalNoopReviewAdapter) and not result.blocked and result.error is None:
        review.mark_feedback_consumed()

    # Post-run output
    _print_post_run(stage, session_id, project_root, result, elapsed)

    # Exit code: non-zero on blocked/error. Quality gate exit code is layered in Task 13.
    return 0 if (not result.blocked and result.error is None) else 1


def _print_post_run(stage, session_id, project_root, result, elapsed):
    status = "OK" if (not result.blocked and result.error is None) else "FAIL"
    mm = int(elapsed) // 60
    ss = int(elapsed) % 60
    print(f"\n✓ Stage {stage.value} {status}   elapsed: {mm}:{ss:02d}")
    print(f"  Session:  {session_id}")
    print(f"  Branch:   a2sdlc/{session_id}")
    print(f"  State:    {project_root}/.a2sdlc/")
```

- [ ] **Step 4: Wire into `cli.py`**

Edit `src/a2sdlc/cli.py` to route `run-stage` to `cli_local.run_stage_entry`:

```python
def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if argv and argv[0] == "run-stage":
        from a2sdlc.cli_local import run_stage_entry
        return run_stage_entry(argv[1:])
    # ... existing dispatch for other subcommands ...
```

- [ ] **Step 5: Add `python-ulid` to deps**

Edit `pyproject.toml`:

```toml
dependencies = [
    # ... existing ...
    "python-ulid>=2.0",
]
```

Run: `uv sync`

- [ ] **Step 6: Run CLI tests — expect PASS**

Run: `make test TEST=tests/test_cli_local.py`
Expected: PASS.

- [ ] **Step 7: Run full test suite**

Run: `make test`
Expected: green. If FakeStageRunner doesn't exist in `tests/fakes.py` yet, add it (minimal: returns a fixed `RunResult` with empty output).

- [ ] **Step 8: Commit**

```bash
git add src/a2sdlc/cli.py src/a2sdlc/cli_local.py tests/test_cli_local.py tests/fakes.py pyproject.toml uv.lock
git commit -m "feat(cli): add run-stage subcommand for local pipeline execution"
```

---

## Task 11: MLflow telemetry sink

**Files:**
- Create: `src/a2sdlc/evaluation/mlflow_sink.py`
- Create: `tests/evaluation/test_mlflow_sink.py`
- Modify: `src/a2sdlc/cli_local.py` (wrap dispatch with MLflow run)
- Modify: `pyproject.toml` (add `mlflow`)

**What changes:** Wraps each `dispatch()` call in an MLflow child run, logs token/cost/turn/duration metrics + tags (`session_id`, `stage`, `git_sha_before`, `dirty_tree_before`). Parent run per session, child run per invocation.

- [ ] **Step 1: Add `mlflow` dep**

Edit `pyproject.toml`:
```toml
dependencies = [
    # ...
    "mlflow>=2.15",
]
```
Run: `uv sync`

- [ ] **Step 2: Write failing test**

Create `tests/evaluation/test_mlflow_sink.py`:

```python
"""Behavior tests for MLflow telemetry sink."""

from pathlib import Path

from a2sdlc.evaluation.mlflow_sink import MlflowSink


def test_mlflow_sink_creates_parent_and_child_runs(tmp_path):
    """GIVEN a fresh MLflow file store
    WHEN MlflowSink logs a stage run for a new session
    THEN a parent run and a child run exist."""
    tracking_uri = f"file://{tmp_path / 'mlflow'}"
    sink = MlflowSink(
        tracking_uri=tracking_uri,
        experiment_name="testrepo",
    )
    with sink.session("sid-1") as session:
        with session.stage_run(stage="spec") as child:
            child.log_metric("tokens_in", 100)
            child.log_metric("cost_usd", 0.01)
            child.log_tag("git_sha_before", "abc123")

    import mlflow
    mlflow.set_tracking_uri(tracking_uri)
    exp = mlflow.get_experiment_by_name("testrepo")
    assert exp is not None
    runs = mlflow.search_runs(experiment_ids=[exp.experiment_id])
    assert len(runs) >= 2  # parent + child


def test_mlflow_sink_unreachable_raises(monkeypatch):
    """GIVEN an invalid tracking URI
    WHEN MlflowSink.verify_reachable is called
    THEN MlflowUnreachableError is raised."""
    from a2sdlc.evaluation.mlflow_sink import MlflowUnreachableError
    import pytest

    sink = MlflowSink(tracking_uri="http://127.0.0.1:1/bad", experiment_name="x")
    with pytest.raises(MlflowUnreachableError):
        sink.verify_reachable(timeout_s=1)
```

- [ ] **Step 3: Run — expect ImportError**

Run: `make test TEST=tests/evaluation/test_mlflow_sink.py`
Expected: FAIL.

- [ ] **Step 4: Implement `mlflow_sink.py`**

Create `src/a2sdlc/evaluation/mlflow_sink.py`:

```python
"""MLflow telemetry sink — parent run per session, child run per stage invocation."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import dataclass

import mlflow


class MlflowUnreachableError(RuntimeError):
    """Raised when the MLflow backend is not reachable."""


@dataclass
class _StageRun:
    run_id: str

    def log_metric(self, key: str, value: float) -> None:
        mlflow.log_metric(key, value, run_id=self.run_id)

    def log_tag(self, key: str, value: str) -> None:
        mlflow.set_tag(key, value)


@dataclass
class _SessionRun:
    parent_run_id: str
    session_id: str

    @contextlib.contextmanager
    def stage_run(self, stage: str) -> Iterator[_StageRun]:
        with mlflow.start_run(nested=True, run_name=f"{self.session_id}:{stage}") as r:
            mlflow.set_tag("stage", stage)
            mlflow.set_tag("session_id", self.session_id)
            yield _StageRun(run_id=r.info.run_id)


class MlflowSink:
    def __init__(self, tracking_uri: str, experiment_name: str) -> None:
        self._uri = tracking_uri
        self._experiment = experiment_name
        mlflow.set_tracking_uri(tracking_uri)

    def verify_reachable(self, timeout_s: float = 5.0) -> None:
        try:
            mlflow.get_tracking_uri()
            # Touch experiment to force backend interaction
            mlflow.set_experiment(self._experiment)
        except Exception as e:
            raise MlflowUnreachableError(str(e)) from e

    @contextlib.contextmanager
    def session(self, session_id: str) -> Iterator[_SessionRun]:
        mlflow.set_experiment(self._experiment)
        with mlflow.start_run(run_name=f"session:{session_id}") as parent:
            yield _SessionRun(parent_run_id=parent.info.run_id, session_id=session_id)
```

- [ ] **Step 5: Integrate into `cli_local.py`**

In `run_stage_entry`, before building adapters:

```python
from a2sdlc.evaluation.mlflow_sink import MlflowSink

tracking_enabled = not args.no_track
sink = None
if tracking_enabled:
    sink = MlflowSink(
        tracking_uri=f"file://{Path.home() / '.a2sdlc' / 'mlflow'}",
        experiment_name=project_root.name,
    )
    sink.verify_reachable()
```

Then wrap dispatch:

```python
if sink:
    with sink.session(session_id) as sess:
        with sess.stage_run(stage=stage.value) as child:
            child.log_tag("git_sha_before", _git_head_sha(project_root))
            child.log_tag("dirty_tree_before", str(_is_dirty(project_root)))
            result = asyncio.run(dispatch(ctx))
            # log metrics from result.stats once dispatch returns
            if result.stats:
                child.log_metric("tokens_in", result.stats.tokens_in)
                child.log_metric("tokens_out", result.stats.tokens_out)
                child.log_metric("cost_usd", result.stats.cost_usd)
                child.log_metric("turns", result.stats.turns)
                child.log_metric("duration_sec", elapsed)
else:
    result = asyncio.run(dispatch(ctx))
```

Add helpers:

```python
def _git_head_sha(root: Path) -> str:
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True,
    )
    return r.stdout.strip()


def _is_dirty(root: Path) -> bool:
    r = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True,
    )
    return bool(r.stdout.strip())
```

> **Note on `DispatchResult.stats`:** verify that `DispatchResult` exposes token/cost stats. If it doesn't, grab them from `exec_result.stats` — look at `dispatch.py:274-282` usage. May require adding `stats` to `DispatchResult`.

- [ ] **Step 6: Run tests**

Run: `make test TEST=tests/evaluation/test_mlflow_sink.py`
Expected: PASS.

Run: `make test`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add src/a2sdlc/evaluation/mlflow_sink.py src/a2sdlc/cli_local.py tests/evaluation/test_mlflow_sink.py pyproject.toml uv.lock
git commit -m "feat(evaluation): log per-stage metrics to local MLflow"
```

---

## Task 12: Quality gate

**Files:**
- Create: `src/a2sdlc/evaluation/quality_gate.py`
- Create: `tests/evaluation/test_quality_gate.py`
- Modify: `src/a2sdlc/cli_local.py` (run gate after implement)

**What changes:** After `run-stage implement`, shell out to `config.quality.check_command` in the project root, log `quality_passed` to MLflow, and propagate to CLI exit code.

- [ ] **Step 1: Write failing tests**

Create `tests/evaluation/test_quality_gate.py`:

```python
"""Quality gate behavior tests."""

from pathlib import Path

from a2sdlc.evaluation.quality_gate import run_quality_gate


def test_quality_gate_passes_when_command_exits_zero(tmp_path):
    """GIVEN check_command='true'
    WHEN run_quality_gate runs
    THEN result.passed is True."""
    result = run_quality_gate(project_root=tmp_path, command="true")
    assert result.passed is True
    assert result.exit_code == 0


def test_quality_gate_fails_when_command_exits_nonzero(tmp_path):
    """GIVEN check_command='false'
    WHEN run_quality_gate runs
    THEN result.passed is False."""
    result = run_quality_gate(project_root=tmp_path, command="false")
    assert result.passed is False
    assert result.exit_code != 0


def test_quality_gate_captures_output(tmp_path):
    """GIVEN a command that writes to stdout
    WHEN run_quality_gate runs
    THEN result.output captures it."""
    result = run_quality_gate(project_root=tmp_path, command="echo hello")
    assert "hello" in result.output
```

- [ ] **Step 2: Run — expect ImportError**

Run: `make test TEST=tests/evaluation/test_quality_gate.py`
Expected: FAIL.

- [ ] **Step 3: Implement `quality_gate.py`**

Create `src/a2sdlc/evaluation/quality_gate.py`:

```python
"""Post-implement quality gate — runs a user-configured check command."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class QualityResult:
    passed: bool
    exit_code: int
    output: str


def run_quality_gate(project_root: Path, command: str) -> QualityResult:
    """Execute `command` in `project_root` via the shell; return pass/fail + output."""
    result = subprocess.run(
        command,
        shell=True,
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    combined = (result.stdout or "") + (result.stderr or "")
    return QualityResult(
        passed=result.returncode == 0,
        exit_code=result.returncode,
        output=combined,
    )
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `make test TEST=tests/evaluation/test_quality_gate.py`
Expected: PASS.

- [ ] **Step 5: Wire into `cli_local.py`**

After a successful IMPLEMENT dispatch, and before `_print_post_run`:

```python
quality = None
if stage == StageName.IMPLEMENT and not result.blocked and result.error is None:
    from a2sdlc.evaluation.quality_gate import run_quality_gate
    quality = run_quality_gate(project_root=project_root, command=cfg.quality.check_command)
    if sink:
        # already inside the session context manager; log on the child run
        child.log_metric("quality_passed", 1 if quality.passed else 0)
        # Artifact: output
        artifact_path = project_root / ".a2sdlc" / "runs" / session_id / "quality.log"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(quality.output)
        mlflow.log_artifact(str(artifact_path))
```

Update exit code:

```python
ok = not result.blocked and result.error is None
if quality is not None and not quality.passed:
    ok = False
return 0 if ok else 1
```

- [ ] **Step 6: Run full test suite**

Run: `make check`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add src/a2sdlc/evaluation/quality_gate.py src/a2sdlc/cli_local.py tests/evaluation/test_quality_gate.py
git commit -m "feat(evaluation): add post-implement quality gate"
```

---

## Task 13: End-to-end smoke test with fake stage runner

**Files:**
- Create: `tests/integration/test_local_runner_e2e.py`
- Modify: `tests/fakes.py` (`FakeStageRunner` returning scripted `RunResult`s)

**What changes:** Drives a full `run-stage spec` → `run-stage implement` sequence on a temp git repo with a fake `StageRunner` (no Claude). Asserts that handover files, pr.json, feedback.json, state.json, branch, and MLflow runs all end up in the right shape.

- [ ] **Step 1: Extend `FakeStageRunner`**

In `tests/fakes.py`, ensure `FakeStageRunner` can be configured with a sequence of `RunResult`s and produces appropriate `finalize_comment` output via a hook.

Key behavior: when `run(...)` is called, the fake writes the corresponding handover content (simulating what a real agent would do) by delegating to an injected callback OR by the test pre-writing the expected handover file before the dispatch.

Simplest: the fake just returns a `RunResult(success=True, output="...", stats=...)` and the test pre-populates expected `.a2sdlc/handover/<stage>.md` before invocation. This isolates adapter + CLI correctness from agent behavior.

- [ ] **Step 2: Write the e2e test**

```python
"""End-to-end smoke: run-stage spec then run-stage implement."""

import json
import subprocess
from pathlib import Path

from a2sdlc.cli_local import run_stage_entry


def test_spec_then_implement_produces_expected_branch_and_files(tmp_path):
    """GIVEN a minimal repo with .a2sdlc/config.yaml
    WHEN run-stage spec then run-stage implement are invoked
    THEN session branch exists, handover files are written, pr.json exists, quality gate runs."""

    # 0. init repo + config + ticket (helper from test_cli_local)
    from tests.test_cli_local import _init_minimal_repo
    ticket = _init_minimal_repo(tmp_path, "Add hello world")

    # Pre-seed handover contents to simulate agent output (FakeStageRunner is a pass-through)
    # Implementation note: the FakeStageRunner will invoke work.finalize_comment with a body,
    # so we just script its return value.

    # 1. run spec
    rc = run_stage_entry(
        argv=["spec", "--session", "e2e", "--ticket", str(ticket),
              "--no-track", str(tmp_path)],
        runner_override="fake",
    )
    assert rc == 0
    assert (tmp_path / ".a2sdlc" / "handover" / "spec.md").exists()
    assert json.loads((tmp_path / ".a2sdlc" / "pr.json").read_text())["pr_number"] == 1

    # 2. run implement
    rc = run_stage_entry(
        argv=["implement", "--session", "e2e", "--no-track", str(tmp_path)],
        runner_override="fake",
    )
    assert rc == 0
    assert (tmp_path / ".a2sdlc" / "handover" / "implement.md").exists()

    # 3. branch check
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert branch == "a2sdlc/e2e"
```

- [ ] **Step 3: Run — expect FAIL until adapters + fake are complete**

Run: `make test TEST=tests/integration/test_local_runner_e2e.py`
Expected: likely passes if previous tasks are done correctly. If failures, debug handover propagation and fake runner shape.

- [ ] **Step 4: Run full `make check`**

Run: `make check`
Expected: green (lint + test + coverage).

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_local_runner_e2e.py tests/fakes.py
git commit -m "test(integration): e2e smoke for local runner spec→implement"
```

---

## Task 14: Documentation and post-run UX polish

**Files:**
- Modify: `README.md` (add Local Runner section)
- Create: `docs/local-runner-usage.md`
- Modify: `src/a2sdlc/cli_local.py` (finalize post-run output)

**What changes:** Docs for end users. Confirm the post-run output matches the spec format.

- [ ] **Step 1: Write a brief README section**

Add to `README.md`:

```markdown
## Local Runner

Run any pipeline stage locally against an existing repo:

```bash
a2sdlc run-stage spec --ticket ticket.md --session my-experiment /path/to/repo
a2sdlc run-stage implement --session my-experiment /path/to/repo
a2sdlc run-stage review --session my-experiment /path/to/repo
a2sdlc run-stage merge --session my-experiment /path/to/repo
```

All state lives on branch `a2sdlc/<session>`. Metrics stream to MLflow at
`~/.a2sdlc/mlflow`. See `docs/local-runner-usage.md` for details.
```

- [ ] **Step 2: Create `docs/local-runner-usage.md`**

Usage walkthrough: config file shape, MLflow UI, inspecting `.a2sdlc/`, parallel runs via multiple clones.

- [ ] **Step 3: Verify post-run output matches the spec**

The spec (section "Post-Run Output") specifies a format. Confirm `cli_local._print_post_run` matches. Adjust if needed.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/local-runner-usage.md src/a2sdlc/cli_local.py
git commit -m "docs(local): add Local Runner usage docs"
```

---

## Self-Review Checklist

Before handing this plan off, run through:

**Spec coverage:**
- [x] Config migration → Task 1
- [x] Progress adapter port + GH Actions + console impls → Tasks 2, 3, 4
- [x] Local git adapter (no origin) → Task 5
- [x] Local review adapter (file-backed PR, synthetic approval, feedback.json) → Task 6
- [x] Local work adapter (file-backed handover, is_feedback flag logic) → Task 7
- [x] Adapter factory → Task 8
- [x] Engine wiring of ProgressAdapter → Task 9
- [x] CLI `run-stage` subcommand → Task 10
- [x] MLflow telemetry (parent/child runs, tags) → Task 11
- [x] Quality gate → Task 12
- [x] E2E smoke → Task 13
- [x] Docs → Task 14

**Deliberate gaps (not in this plan):**
- Refactoring existing Jira/GitHub adapters into the protocol shape more formally (only if lint catches drift).
- Automated branch/session cleanup (`a2sdlc sessions prune`) — explicit non-goal.
- Task manifest / Taskmaster decomposition — explicit non-goal.

**Type consistency:** adapter signatures in tasks 5–7 mirror `adapters/work.py` and `adapters/review.py` exactly. `ProgressAdapter` method names match across tasks 2, 3, 4, 9.

**Risk areas:**
- Task 9 (ProgressAdapter wiring) may bleed into many existing test files. Budget accordingly.
- Task 11's `DispatchResult.stats` access assumes the field exists; verify and extend if needed.
- `FakeStageRunner`'s current signature is inherited; Task 13 may require small adjustments.
