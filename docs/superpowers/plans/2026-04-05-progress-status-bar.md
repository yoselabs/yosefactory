# Progress Status Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a status bar (model, branch, context %, cost, tokens, duration, turns), tool target extraction, and persistent skill milestones to GitHub issue progress comments.

**Architecture:** New `ProgressState` dataclass in `runner.py` accumulates metrics during streaming. Three rendering functions (`format_progress`, `format_final`, `format_error`) produce markdown for in-progress, completion, and failure comments. Dispatch passes branch name to runner and uses new formatters instead of `format_cost()`.

**Tech Stack:** Python dataclasses, Claude Agent SDK streaming types, markdown table rendering.

**Spec:** `docs/superpowers/specs/2026-04-05-progress-status-bar-design.md`

---

### Task 1: Add data model classes (ToolEntry, Milestone, ProgressState)

**Files:**
- Modify: `src/a2sdlc/runner.py:1-40`
- Test: `tests/test_runner.py`

- [ ] **Step 1: Write tests for new dataclasses**

Add to `tests/test_runner.py`:

```python
from a2sdlc.runner import Milestone, ProgressState, ToolEntry


@pytest.mark.unit
class TestToolEntry:
    def test_create(self) -> None:
        entry = ToolEntry(timestamp=1.5, name="Read", target="src/app.py")
        assert entry.timestamp == 1.5
        assert entry.name == "Read"
        assert entry.target == "src/app.py"


@pytest.mark.unit
class TestMilestone:
    def test_create(self) -> None:
        ms = Milestone(timestamp=42.0, label="brainstorming invoked")
        assert ms.timestamp == 42.0
        assert ms.label == "brainstorming invoked"


@pytest.mark.unit
class TestProgressState:
    def test_defaults(self) -> None:
        ps = ProgressState(
            model="claude-sonnet-4-6",
            branch="feat/T-1",
            max_turns=120,
            context_window=200_000,
            project_root="/tmp/test",
            start_time=1000.0,
        )
        assert ps.input_tokens == 0
        assert ps.output_tokens == 0
        assert ps.total_cost_usd == 0.0
        assert ps.num_turns == 0
        assert ps.tool_log == []
        assert ps.milestones == []

    def test_accumulate(self) -> None:
        ps = ProgressState(
            model="claude-sonnet-4-6",
            branch="feat/T-1",
            max_turns=120,
            context_window=200_000,
            project_root="/tmp/test",
            start_time=1000.0,
        )
        ps.tool_log.append(ToolEntry(timestamp=1.0, name="Read", target="f.py"))
        ps.milestones.append(Milestone(timestamp=2.0, label="skill invoked"))
        ps.input_tokens = 5000
        ps.num_turns = 3
        assert len(ps.tool_log) == 1
        assert len(ps.milestones) == 1
        assert ps.input_tokens == 5000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_runner.py::TestToolEntry tests/test_runner.py::TestMilestone tests/test_runner.py::TestProgressState -v`
Expected: ImportError — `ToolEntry`, `Milestone`, `ProgressState` not defined.

- [ ] **Step 3: Implement the dataclasses**

In `src/a2sdlc/runner.py`, add after the existing imports and before `RunResult`:

```python
@dataclass
class ToolEntry:
    """Single tool call with context."""

    timestamp: float  # seconds since stage start
    name: str  # tool name (Read, Edit, Bash, etc.)
    target: str  # extracted target (file path, command preview, pattern)


@dataclass
class Milestone:
    """Persistent event that survives comment overwrites."""

    timestamp: float  # seconds since stage start
    label: str  # e.g. "brainstorming invoked"


@dataclass
class ProgressState:
    """Accumulated metrics during stage execution."""

    model: str
    branch: str
    max_turns: int
    context_window: int  # total context window size in tokens
    project_root: str  # for shortening file paths in tool targets
    start_time: float  # time.time() at stage start

    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_usd: float = 0.0
    num_turns: int = 0
    tool_log: list[ToolEntry] = field(default_factory=list)
    milestones: list[Milestone] = field(default_factory=list)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_runner.py::TestToolEntry tests/test_runner.py::TestMilestone tests/test_runner.py::TestProgressState -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/a2sdlc/runner.py tests/test_runner.py
git commit -m "feat: add ToolEntry, Milestone, ProgressState dataclasses"
```

---

### Task 2: Add context window map and helper functions

**Files:**
- Modify: `src/a2sdlc/runner.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: Write tests for helper functions**

Add to `tests/test_runner.py`:

```python
from a2sdlc.runner import (
    _extract_target,
    _format_duration,
    _format_tokens,
    _shorten_path,
    context_window_for_model,
)


@pytest.mark.unit
class TestContextWindow:
    def test_known_model(self) -> None:
        assert context_window_for_model("claude-sonnet-4-6") == 200_000

    def test_known_opus(self) -> None:
        assert context_window_for_model("claude-opus-4-6") == 1_000_000

    def test_unknown_model_returns_none(self) -> None:
        assert context_window_for_model("gpt-4o") is None


@pytest.mark.unit
class TestShortenPath:
    def test_strips_project_root(self) -> None:
        assert _shorten_path("/tmp/project/src/app.py", "/tmp/project") == "src/app.py"

    def test_no_common_prefix(self) -> None:
        assert _shorten_path("/other/path/file.py", "/tmp/project") == "/other/path/file.py"

    def test_empty_path(self) -> None:
        assert _shorten_path("", "/tmp/project") == ""

    def test_glob_pattern(self) -> None:
        assert _shorten_path("**/*.py", "/tmp/project") == "**/*.py"


@pytest.mark.unit
class TestExtractTarget:
    def test_read(self) -> None:
        result = _extract_target("Read", {"file_path": "/tmp/p/src/app.py"}, "/tmp/p")
        assert result == "src/app.py"

    def test_edit(self) -> None:
        result = _extract_target("Edit", {"file_path": "/tmp/p/src/app.py"}, "/tmp/p")
        assert result == "src/app.py"

    def test_bash(self) -> None:
        result = _extract_target("Bash", {"command": "pytest tests/ -v"}, "/tmp/p")
        assert result == "`pytest tests/ -v`"

    def test_bash_truncates(self) -> None:
        long_cmd = "x" * 100
        result = _extract_target("Bash", {"command": long_cmd}, "/tmp/p")
        assert result == f"`{'x' * 60}`"

    def test_grep(self) -> None:
        result = _extract_target("Grep", {"pattern": "handle_event"}, "/tmp/p")
        assert result == "handle_event"

    def test_glob(self) -> None:
        result = _extract_target("Glob", {"pattern": "**/*.py"}, "/tmp/p")
        assert result == "**/*.py"

    def test_write(self) -> None:
        result = _extract_target("Write", {"file_path": "/tmp/p/new.py"}, "/tmp/p")
        assert result == "new.py"

    def test_skill(self) -> None:
        result = _extract_target("Skill", {"skill": "brainstorming"}, "/tmp/p")
        assert result == "brainstorming"

    def test_unknown_tool(self) -> None:
        result = _extract_target("CustomTool", {"arg": "val"}, "/tmp/p")
        assert result == ""

    def test_empty_input(self) -> None:
        result = _extract_target("Read", {}, "/tmp/p")
        assert result == ""


@pytest.mark.unit
class TestFormatDuration:
    def test_seconds(self) -> None:
        assert _format_duration(45.0) == "45s"

    def test_minutes_seconds(self) -> None:
        assert _format_duration(135.0) == "2m 15s"

    def test_hours_minutes(self) -> None:
        assert _format_duration(3720.0) == "1h 2m"

    def test_zero(self) -> None:
        assert _format_duration(0.0) == "0s"


@pytest.mark.unit
class TestFormatTokens:
    def test_thousands(self) -> None:
        assert _format_tokens(45000) == "45k"

    def test_hundreds_of_thousands(self) -> None:
        assert _format_tokens(312000) == "312k"

    def test_small(self) -> None:
        assert _format_tokens(500) == "1k"

    def test_zero(self) -> None:
        assert _format_tokens(0) == "0k"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_runner.py::TestContextWindow tests/test_runner.py::TestShortenPath tests/test_runner.py::TestExtractTarget tests/test_runner.py::TestFormatDuration tests/test_runner.py::TestFormatTokens -v`
Expected: ImportError — functions not defined.

- [ ] **Step 3: Implement helper functions**

In `src/a2sdlc/runner.py`, add after the `ProgressState` dataclass and before `RunResult`:

```python
# ── Context window sizes ───────────────────────────────────────────

_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-sonnet-4-6": 200_000,
    "claude-opus-4-6": 1_000_000,
    "claude-haiku-4-5-20251001": 200_000,
}


def context_window_for_model(model: str) -> int | None:
    """Return context window size for a model, or None if unknown."""
    return _CONTEXT_WINDOWS.get(model)


# ── Formatting helpers ─────────────────────────────────────────────


def _shorten_path(path: str, project_root: str) -> str:
    """Strip project root prefix from a file path."""
    if not path:
        return ""
    if path.startswith(project_root):
        shortened = path[len(project_root) :]
        return shortened.lstrip("/")
    return path


def _extract_target(name: str, inp: dict, project_root: str) -> str:
    """Extract a human-readable target from tool input."""
    if name in ("Read", "Edit", "Write"):
        path = inp.get("file_path", "")
        return _shorten_path(path, project_root) if path else ""
    if name in ("Glob", "Grep"):
        return inp.get("pattern", "") or inp.get("path", "") or ""
    if name == "Bash":
        cmd = inp.get("command", "")
        return f"`{cmd[:60]}`" if cmd else ""
    if name == "Skill":
        return inp.get("skill", "")
    return ""


def _format_duration(seconds: float) -> str:
    """Format duration as human-readable string."""
    s = int(seconds)
    if s >= 3600:
        return f"{s // 3600}h {(s % 3600) // 60}m"
    if s >= 60:
        return f"{s // 60}m {s % 60}s"
    return f"{s}s"


def _format_tokens(tokens: int) -> str:
    """Format token count as compact string (e.g. '45k')."""
    k = max(1, round(tokens / 1000)) if tokens > 0 else 0
    return f"{k}k"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_runner.py::TestContextWindow tests/test_runner.py::TestShortenPath tests/test_runner.py::TestExtractTarget tests/test_runner.py::TestFormatDuration tests/test_runner.py::TestFormatTokens -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/a2sdlc/runner.py tests/test_runner.py
git commit -m "feat: add context window map and formatting helpers"
```

---

### Task 3: Implement rendering functions (format_progress, format_final, format_error)

**Files:**
- Modify: `src/a2sdlc/runner.py`
- Modify: `tests/test_runner.py`

- [ ] **Step 1: Write tests for format_status_bar (internal helper)**

Add to `tests/test_runner.py`:

```python
from a2sdlc.runner import _format_status_bar, _format_milestones


@pytest.mark.unit
class TestFormatStatusBar:
    def test_full_bar(self) -> None:
        bar = _format_status_bar(
            model="claude-sonnet-4-6",
            branch="feat/T-1",
            input_tokens=45000,
            output_tokens=12000,
            total_cost_usd=0.72,
            duration_seconds=135.0,
            num_turns=12,
            max_turns=120,
            context_window=200_000,
        )
        assert "claude-sonnet-4-6" in bar
        assert "feat/T-1" in bar
        assert "45k/200k" in bar
        assert "23%" in bar  # 45000/200000
        assert "$0.72" in bar
        assert "45k in" in bar
        assert "12k out" in bar
        assert "2m 15s" in bar
        assert "12/120" in bar
        # Should be a markdown table
        assert bar.startswith("| Model")
        assert "|---|" in bar

    def test_unknown_context_window(self) -> None:
        bar = _format_status_bar(
            model="custom-model",
            branch="main",
            input_tokens=5000,
            output_tokens=1000,
            total_cost_usd=0.01,
            duration_seconds=10.0,
            num_turns=2,
            max_turns=25,
            context_window=None,
        )
        assert "custom-model" in bar
        assert "5k" in bar
        # No percentage when context_window is None
        assert "%" not in bar

    def test_unknown_tokens(self) -> None:
        """When tokens are 0 (unknown during streaming), show dash."""
        bar = _format_status_bar(
            model="claude-sonnet-4-6",
            branch="feat/T-1",
            input_tokens=0,
            output_tokens=0,
            total_cost_usd=0.0,
            duration_seconds=30.0,
            num_turns=5,
            max_turns=120,
            context_window=200_000,
        )
        assert "—" in bar  # em dash for unknown values


@pytest.mark.unit
class TestFormatMilestones:
    def test_empty(self) -> None:
        assert _format_milestones([]) == ""

    def test_single(self) -> None:
        ms = [Milestone(timestamp=42.0, label="brainstorming invoked")]
        text = _format_milestones(ms)
        assert "📌" in text
        assert "0:42" in text
        assert "brainstorming invoked" in text

    def test_multiple(self) -> None:
        ms = [
            Milestone(timestamp=42.0, label="brainstorming invoked"),
            Milestone(timestamp=135.0, label="writing-plans invoked"),
        ]
        text = _format_milestones(ms)
        assert text.count("📌") == 2
        assert "0:42" in text
        assert "2:15" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_runner.py::TestFormatStatusBar tests/test_runner.py::TestFormatMilestones -v`
Expected: ImportError.

- [ ] **Step 3: Implement _format_status_bar and _format_milestones**

In `src/a2sdlc/runner.py`, add after `_format_tokens`:

```python
def _format_milestone_time(seconds: float) -> str:
    """Format timestamp as M:SS for milestone display."""
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m}:{s:02d}"


def _format_status_bar(
    *,
    model: str,
    branch: str,
    input_tokens: int,
    output_tokens: int,
    total_cost_usd: float,
    duration_seconds: float,
    num_turns: int,
    max_turns: int,
    context_window: int | None,
) -> str:
    """Render a single-row markdown table status bar."""
    # Tokens — show dash if unknown (0 during early streaming)
    if input_tokens == 0 and output_tokens == 0 and total_cost_usd == 0.0:
        tokens_str = "—"
        cost_str = "—"
        context_str = "—"
    else:
        tokens_str = f"{_format_tokens(input_tokens)} in / {_format_tokens(output_tokens)} out"
        cost_str = f"${total_cost_usd:.2f}"
        if context_window:
            pct = int(input_tokens / context_window * 100)
            ctx_k = context_window // 1000
            context_str = f"{_format_tokens(input_tokens)}/{ctx_k}k ({pct}%)"
        else:
            context_str = _format_tokens(input_tokens)

    duration_str = _format_duration(duration_seconds)
    turns_str = f"{num_turns}/{max_turns}"

    header = "| Model | Branch | Context | Cost | Tokens | Duration | Turns |"
    sep = "|-------|--------|---------|------|--------|----------|-------|"
    row = f"| {model} | {branch} | {context_str} | {cost_str} | {tokens_str} | {duration_str} | {turns_str} |"
    return f"{header}\n{sep}\n{row}"


def _format_milestones(milestones: list[Milestone]) -> str:
    """Render milestones as persistent pin lines."""
    if not milestones:
        return ""
    lines = []
    for ms in milestones:
        time_str = _format_milestone_time(ms.timestamp)
        lines.append(f"📌 {time_str} — {ms.label}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_runner.py::TestFormatStatusBar tests/test_runner.py::TestFormatMilestones -v`
Expected: All PASS.

- [ ] **Step 5: Write tests for format_progress, format_final, format_error**

Add to `tests/test_runner.py`. Update the existing `TestFormatProgress` class — replace it entirely:

```python
@pytest.mark.unit
class TestFormatProgress:
    def _make_progress(self, **overrides) -> ProgressState:
        defaults = dict(
            model="claude-sonnet-4-6",
            branch="feat/T-1",
            max_turns=120,
            context_window=200_000,
            project_root="/tmp/test",
            start_time=1000.0,
        )
        defaults.update(overrides)
        return ProgressState(**defaults)

    def test_basic_progress(self) -> None:
        ps = self._make_progress()
        ps.input_tokens = 45000
        ps.output_tokens = 12000
        ps.total_cost_usd = 0.72
        ps.num_turns = 12
        ps.tool_log = [
            ToolEntry(timestamp=1.0, name="Read", target="src/app.py"),
            ToolEntry(timestamp=2.0, name="Edit", target="src/app.py"),
        ]
        text = format_progress("implement", ps, elapsed=135.0)
        assert "⏳ **implement** in progress..." in text
        assert "claude-sonnet-4-6" in text
        assert "feat/T-1" in text
        assert "| Read | src/app.py |" in text
        assert "| Edit | src/app.py |" in text

    def test_tool_log_truncation(self) -> None:
        ps = self._make_progress()
        ps.tool_log = [
            ToolEntry(timestamp=float(i), name=f"Tool-{i}", target=f"f{i}.py")
            for i in range(25)
        ]
        text = format_progress("implement", ps, elapsed=60.0)
        assert "*(15 earlier)*" in text
        assert "Tool-24" in text
        assert "Tool-14" not in text

    def test_milestones_shown(self) -> None:
        ps = self._make_progress()
        ps.milestones = [Milestone(timestamp=42.0, label="brainstorming invoked")]
        text = format_progress("spec", ps, elapsed=60.0)
        assert "📌 0:42 — brainstorming invoked" in text

    def test_empty_log(self) -> None:
        ps = self._make_progress()
        text = format_progress("spec", ps, elapsed=0.0)
        assert "⏳ **spec** in progress..." in text


@pytest.mark.unit
class TestFormatFinal:
    def test_success(self) -> None:
        result = RunResult(
            success=True,
            output="Done implementing.",
            input_tokens=312000,
            output_tokens=24000,
            total_cost_usd=2.14,
            duration_ms=522000,
            num_turns=45,
        )
        milestones = [
            Milestone(timestamp=42.0, label="brainstorming invoked"),
            Milestone(timestamp=390.0, label="requesting-code-review invoked"),
        ]
        text = format_final(
            result,
            milestones=milestones,
            model="claude-sonnet-4-6",
            branch="feat/T-1",
            max_turns=120,
            context_window=200_000,
        )
        assert "Done implementing." in text
        assert "---" in text
        assert "312k" in text
        assert "$2.14" in text
        assert "📌 0:42 — brainstorming invoked" in text
        assert "📌 6:30 — requesting-code-review invoked" in text

    def test_no_milestones(self) -> None:
        result = RunResult(
            success=True,
            output="Done.",
            input_tokens=1000,
            output_tokens=500,
            total_cost_usd=0.05,
            duration_ms=30000,
        )
        text = format_final(
            result,
            milestones=[],
            model="claude-sonnet-4-6",
            branch="feat/T-1",
            max_turns=120,
            context_window=200_000,
        )
        assert "Done." in text
        assert "📌" not in text


@pytest.mark.unit
class TestFormatError:
    def test_error_with_milestones(self) -> None:
        result = RunResult(
            success=False,
            error="timeout (60min)",
            input_tokens=100000,
            output_tokens=5000,
            total_cost_usd=0.50,
            duration_ms=3600000,
        )
        milestones = [Milestone(timestamp=42.0, label="brainstorming invoked")]
        text = format_error(
            result,
            milestones=milestones,
            model="claude-sonnet-4-6",
            branch="feat/T-1",
            max_turns=120,
            context_window=200_000,
        )
        assert "🚨" in text
        assert "timeout (60min)" in text
        assert "claude-sonnet-4-6" in text
        assert "📌 0:42 — brainstorming invoked" in text

    def test_error_no_milestones(self) -> None:
        result = RunResult(success=False, error="sdk_error")
        text = format_error(
            result,
            milestones=[],
            model="claude-sonnet-4-6",
            branch="feat/T-1",
            max_turns=25,
            context_window=200_000,
        )
        assert "🚨" in text
        assert "sdk_error" in text
        assert "📌" not in text
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `pytest tests/test_runner.py::TestFormatProgress tests/test_runner.py::TestFormatFinal tests/test_runner.py::TestFormatError -v`
Expected: Failures — new signatures and functions not yet implemented.

- [ ] **Step 7: Implement format_progress, format_final, format_error**

In `src/a2sdlc/runner.py`, **replace** the existing `format_progress` function and add `format_final` and `format_error`. Remove the old `format_cost` function.

Replace the entire `# ── Progress tracking` section with:

```python
# ── Progress tracking ───────────────────────────────────────────────


def format_progress(stage: str, progress: ProgressState, *, elapsed: float | None = None) -> str:
    """Build a progress comment body from ProgressState."""
    if elapsed is None:
        elapsed = time.time() - progress.start_time

    parts = [f"⏳ **{stage}** in progress...\n"]

    # Status bar
    parts.append(
        _format_status_bar(
            model=progress.model,
            branch=progress.branch,
            input_tokens=progress.input_tokens,
            output_tokens=progress.output_tokens,
            total_cost_usd=progress.total_cost_usd,
            duration_seconds=elapsed,
            num_turns=progress.num_turns,
            max_turns=progress.max_turns,
            context_window=progress.context_window if progress.context_window > 0 else None,
        )
    )

    # Milestones
    ms_text = _format_milestones(progress.milestones)
    if ms_text:
        parts.append(f"\n{ms_text}")

    # Tool table (last 10)
    if progress.tool_log:
        parts.append("")
        header = "| Time | Tool | Target |"
        sep = "|------|------|--------|"
        parts.append(header)
        parts.append(sep)
        total = len(progress.tool_log)
        if total > 10:
            parts.append(f"| ... | | *({total - 10} earlier)* |")
        for entry in progress.tool_log[-10:]:
            t = _format_milestone_time(entry.timestamp)
            parts.append(f"| {t} | {entry.name} | {entry.target} |")

    return "\n".join(parts)


def format_final(
    result: RunResult,
    *,
    milestones: list[Milestone],
    model: str,
    branch: str,
    max_turns: int,
    context_window: int | None,
) -> str:
    """Build the final completion comment with status bar and milestones."""
    body = result.output or ""
    duration_s = result.duration_ms / 1000

    bar = _format_status_bar(
        model=model,
        branch=branch,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        total_cost_usd=result.total_cost_usd,
        duration_seconds=duration_s,
        num_turns=result.num_turns,
        max_turns=max_turns,
        context_window=context_window,
    )

    parts = [body, "\n---\n", bar]

    ms_text = _format_milestones(milestones)
    if ms_text:
        parts.append(f"\n{ms_text}")

    return "\n".join(parts)


def format_error(
    result: RunResult,
    *,
    milestones: list[Milestone],
    model: str,
    branch: str,
    max_turns: int,
    context_window: int | None,
) -> str:
    """Build an error comment with status bar and milestones."""
    duration_s = result.duration_ms / 1000

    bar = _format_status_bar(
        model=model,
        branch=branch,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        total_cost_usd=result.total_cost_usd,
        duration_seconds=duration_s,
        num_turns=result.num_turns,
        max_turns=max_turns,
        context_window=context_window,
    )

    parts = [f"🚨 **{result.error}**", "\n---\n", bar]

    ms_text = _format_milestones(milestones)
    if ms_text:
        parts.append(f"\n{ms_text}")

    return "\n".join(parts)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_runner.py::TestFormatProgress tests/test_runner.py::TestFormatFinal tests/test_runner.py::TestFormatError tests/test_runner.py::TestFormatStatusBar tests/test_runner.py::TestFormatMilestones -v`
Expected: All PASS.

- [ ] **Step 9: Commit**

```bash
git add src/a2sdlc/runner.py tests/test_runner.py
git commit -m "feat: add format_progress, format_final, format_error with status bar"
```

---

### Task 4: Update _handle_assistant_message to populate ProgressState

**Files:**
- Modify: `src/a2sdlc/runner.py:201-223`
- Test: `tests/test_runner.py`

- [ ] **Step 1: Write tests for updated handler**

Add to `tests/test_runner.py`:

```python
from a2sdlc.runner import _handle_assistant_message


@pytest.mark.unit
class TestHandleAssistantMessage:
    def _make_progress(self) -> ProgressState:
        return ProgressState(
            model="claude-sonnet-4-6",
            branch="feat/T-1",
            max_turns=120,
            context_window=200_000,
            project_root="/tmp/project",
            start_time=1000.0,
        )

    def test_tool_entry_with_target(self) -> None:
        from claude_agent_sdk.types import AssistantMessage, ToolUseBlock

        msg = MagicMock(spec=AssistantMessage)
        block = MagicMock(spec=ToolUseBlock)
        block.name = "Read"
        block.input = {"file_path": "/tmp/project/src/app.py"}
        msg.content = [block]
        msg.usage = None

        progress = self._make_progress()
        _handle_assistant_message(msg, progress, current_time=1001.5)

        assert len(progress.tool_log) == 1
        assert progress.tool_log[0].name == "Read"
        assert progress.tool_log[0].target == "src/app.py"
        assert progress.tool_log[0].timestamp == 1.5

    def test_skill_creates_milestone(self) -> None:
        from claude_agent_sdk.types import AssistantMessage, ToolUseBlock

        msg = MagicMock(spec=AssistantMessage)
        block = MagicMock(spec=ToolUseBlock)
        block.name = "Skill"
        block.input = {"skill": "brainstorming"}
        msg.content = [block]
        msg.usage = None

        progress = self._make_progress()
        _handle_assistant_message(msg, progress, current_time=1042.0)

        assert len(progress.milestones) == 1
        assert progress.milestones[0].label == "brainstorming invoked"
        assert progress.milestones[0].timestamp == 42.0
        # Also appears in tool_log
        assert len(progress.tool_log) == 1

    def test_usage_accumulation(self) -> None:
        from claude_agent_sdk.types import AssistantMessage, TextBlock

        msg = MagicMock(spec=AssistantMessage)
        block = MagicMock(spec=TextBlock)
        block.text = "thinking..."
        msg.content = [block]
        msg.usage = {"input_tokens": 5000, "output_tokens": 1200}

        progress = self._make_progress()
        _handle_assistant_message(msg, progress, current_time=1010.0)

        assert progress.input_tokens == 5000
        assert progress.output_tokens == 1200

    def test_usage_as_object(self) -> None:
        from claude_agent_sdk.types import AssistantMessage, TextBlock

        msg = MagicMock(spec=AssistantMessage)
        block = MagicMock(spec=TextBlock)
        block.text = "thinking..."
        msg.content = [block]
        usage_obj = MagicMock()
        usage_obj.input_tokens = 8000
        usage_obj.output_tokens = 2000
        msg.usage = usage_obj

        progress = self._make_progress()
        _handle_assistant_message(msg, progress, current_time=1010.0)

        assert progress.input_tokens == 8000
        assert progress.output_tokens == 2000

    def test_cost_accumulation(self) -> None:
        from claude_agent_sdk.types import AssistantMessage, TextBlock

        msg = MagicMock(spec=AssistantMessage)
        block = MagicMock(spec=TextBlock)
        block.text = "thinking..."
        msg.content = [block]
        msg.usage = None
        msg.total_cost_usd = 0.42

        progress = self._make_progress()
        _handle_assistant_message(msg, progress, current_time=1010.0)

        assert progress.total_cost_usd == 0.42

    def test_no_usage(self) -> None:
        from claude_agent_sdk.types import AssistantMessage, TextBlock

        msg = MagicMock(spec=AssistantMessage)
        block = MagicMock(spec=TextBlock)
        block.text = "thinking..."
        msg.content = [block]
        msg.usage = None

        progress = self._make_progress()
        _handle_assistant_message(msg, progress, current_time=1010.0)

        assert progress.input_tokens == 0
        assert progress.output_tokens == 0

    def test_no_content(self) -> None:
        from claude_agent_sdk.types import AssistantMessage

        msg = MagicMock(spec=AssistantMessage)
        msg.content = None
        msg.usage = None

        progress = self._make_progress()
        _handle_assistant_message(msg, progress, current_time=1010.0)

        assert len(progress.tool_log) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_runner.py::TestHandleAssistantMessage -v`
Expected: TypeError — `_handle_assistant_message` has wrong signature (still takes `tool_log: list[str]`).

- [ ] **Step 3: Update _handle_assistant_message**

Replace the existing `_handle_assistant_message` function in `src/a2sdlc/runner.py`:

```python
def _get_tokens(usage: object, field: str) -> int:
    """Safely extract token count from usage (dict or object)."""
    if isinstance(usage, dict):
        return usage.get(field, 0) or 0
    return getattr(usage, field, 0) or 0


def _handle_assistant_message(
    msg: object, progress: ProgressState, *, current_time: float | None = None,
) -> None:
    """Extract tool calls, usage, and milestones from an AssistantMessage."""
    now = current_time if current_time is not None else time.time()
    elapsed = now - progress.start_time

    # Accumulate usage
    usage = getattr(msg, "usage", None)
    if usage:
        progress.input_tokens = _get_tokens(usage, "input_tokens")
        progress.output_tokens = _get_tokens(usage, "output_tokens")
    cost = getattr(msg, "total_cost_usd", None)
    if cost:
        progress.total_cost_usd = cost

    # Process content blocks
    content = getattr(msg, "content", None)
    if not content:
        return
    for block in content:
        if isinstance(block, ToolUseBlock):
            name = block.name or "unknown"
            inp = block.input if isinstance(block.input, dict) else {}
            target = _extract_target(name, inp, progress.project_root)

            progress.tool_log.append(
                ToolEntry(timestamp=elapsed, name=name, target=target)
            )

            # Skill → milestone
            if name == "Skill":
                skill_name = inp.get("skill", "unknown")
                progress.milestones.append(
                    Milestone(timestamp=elapsed, label=f"{skill_name} invoked")
                )

            # GH Actions collapsible group
            print(f"::group::Tool: {name}")  # noqa: T201
            console.log(f"[cyan]Tool:[/cyan] {name}")
            if isinstance(block.input, dict):
                for k, v in block.input.items():
                    console.log(f"  [dim]{k}:[/dim] {str(v)[:100]}")
            print("::endgroup::")  # noqa: T201
        elif isinstance(block, TextBlock):
            if block.text:
                preview = block.text[:200].replace("\n", " ")
                console.log(f"[dim]{preview}[/dim]")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_runner.py::TestHandleAssistantMessage -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/a2sdlc/runner.py tests/test_runner.py
git commit -m "feat: update _handle_assistant_message to populate ProgressState"
```

---

### Task 5: Update run_stage to use ProgressState and add branch parameter

**Files:**
- Modify: `src/a2sdlc/runner.py:74-198`
- Modify: `src/a2sdlc/runner.py:27-39` (RunResult)
- Test: `tests/test_runner.py`

- [ ] **Step 1: Add progress field to RunResult and update run_stage**

In `src/a2sdlc/runner.py`, add `progress` field to `RunResult`:

```python
@dataclass
class RunResult:
    """Normalized result from a stage execution."""

    success: bool
    output: str = ""
    error: str | None = None
    session_id: str = ""
    total_cost_usd: float = 0.0
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    num_turns: int = 0
    tool_log: list[str] = field(default_factory=list)
    progress: ProgressState | None = None
```

Update `run_stage` signature — add `branch` parameter, create `ProgressState`, update streaming loop, attach progress to result:

```python
async def run_stage(
    user_prompt: str,
    system_prompt: str,
    config: StageConfig,
    ticket_key: str,
    stage: str,
    project_root: str,
    is_resume: bool = False,
    on_progress: Callable[[str], None] | None = None,
    branch: str = "",
) -> RunResult:
    """Run a pipeline stage using the Claude Agent SDK."""
    from claude_agent_sdk import ClaudeAgentOptions, query  # noqa: PLC0415

    sid = get_session_id(ticket_key, stage)
    logger.info(
        "Running stage: ticket=%s stage=%s session=%s resume=%s",
        ticket_key,
        stage,
        sid,
        is_resume,
    )

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        permission_mode="bypassPermissions",
        allowed_tools=config.allowed_tools,
        max_turns=config.max_turns,
        model=config.model,
        cwd=project_root,
    )
    if is_resume:
        options.resume = sid
    else:
        options.session_id = sid

    start_time = time.time()
    progress = ProgressState(
        model=config.model,
        branch=branch,
        max_turns=config.max_turns,
        context_window=context_window_for_model(config.model) or 0,
        project_root=project_root,
        start_time=start_time,
    )
    last_progress_update = 0.0
    result_msg: ResultMessage | None = None

    timeout_seconds = config.timeout_minutes * 60

    try:

        async def _stream() -> None:
            nonlocal result_msg, last_progress_update
            async for msg in query(prompt=user_prompt, options=options):
                if isinstance(msg, AssistantMessage):
                    progress.num_turns += 1
                    _handle_assistant_message(msg, progress)

                    # Throttled progress update
                    if on_progress:
                        now = time.time()
                        if now - last_progress_update >= 5:
                            on_progress(format_progress(stage, progress))
                            last_progress_update = now

                elif isinstance(msg, ResultMessage):
                    result_msg = msg

        await asyncio.wait_for(_stream(), timeout=timeout_seconds)
    except TimeoutError:
        logger.error(
            "Stage %s timed out after %d minutes", stage, config.timeout_minutes
        )
        return RunResult(
            success=False,
            error=f"timeout ({config.timeout_minutes}min)",
            session_id=sid,
            tool_log=[e.name for e in progress.tool_log],
            progress=progress,
        )
    except Exception as exc:
        logger.exception("SDK error during stage %s", stage)
        return RunResult(
            success=False,
            error=f"sdk_error: {type(exc).__name__}: {exc}",
            session_id=sid,
            tool_log=[e.name for e in progress.tool_log],
            progress=progress,
        )

    if result_msg is None:
        return RunResult(
            success=False,
            error="no_result",
            session_id=sid,
            tool_log=[e.name for e in progress.tool_log],
            progress=progress,
        )

    # Extract usage data — usage may be a dict or an object.
    usage = result_msg.usage or {}
    if isinstance(usage, dict):
        input_tokens = usage.get("input_tokens", 0) or 0
        output_tokens = usage.get("output_tokens", 0) or 0
    else:
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0

    success = getattr(result_msg, "subtype", "") == "success"

    run_result = RunResult(
        success=success,
        output=getattr(result_msg, "result", "") or "",
        error=None if success else getattr(result_msg, "subtype", "unknown"),
        session_id=getattr(result_msg, "session_id", sid) or sid,
        total_cost_usd=getattr(result_msg, "total_cost_usd", 0) or 0,
        duration_ms=getattr(result_msg, "duration_ms", 0) or 0,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        num_turns=getattr(result_msg, "num_turns", 0) or 0,
        tool_log=[e.name for e in progress.tool_log],
        progress=progress,
    )

    logger.info(
        "Stage complete: success=%s cost=$%.4f turns=%d tools=%d output_len=%d",
        run_result.success,
        run_result.total_cost_usd,
        run_result.num_turns,
        len(progress.tool_log),
        len(run_result.output),
    )
    return run_result
```

- [ ] **Step 2: Run existing tests to verify they still pass**

Run: `pytest tests/test_runner.py -v`
Expected: All PASS. The `branch` param defaults to `""`, so existing callers don't break. `tool_log` on `RunResult` is still a `list[str]` for backward compat (populated from `progress.tool_log` names). The existing `test_success_flow` checks `result.tool_log == ["Read", "Write"]` — this still works because we populate from `progress.tool_log` entry names.

Note: The existing `test_success_flow` mock's `_make_assistant_message` creates `ToolUseBlock` mocks with `block.input = {}`. The updated `_handle_assistant_message` calls `_extract_target` which handles empty dict gracefully. The `progress.num_turns` increment happens on each `AssistantMessage`, so we also need to verify mocks have `usage` attribute. Check if `_make_assistant_message` mocks need `msg.usage = None` and `msg.total_cost_usd = None` — if they're `MagicMock(spec=AssistantMessage)`, getattr will return MagicMock for unset attrs. Add explicit `msg.usage = None` to the existing `_make_assistant_message` helper:

In `tests/test_runner.py`, update `_make_assistant_message`:

```python
def _make_assistant_message(tool_names: list[str] | None = None) -> MagicMock:
    """Build a mock AssistantMessage with optional tool use blocks."""
    from claude_agent_sdk.types import AssistantMessage, TextBlock, ToolUseBlock

    msg = MagicMock(spec=AssistantMessage)
    msg.usage = None
    msg.total_cost_usd = None
    blocks = []
    if tool_names:
        for name in tool_names:
            block = MagicMock(spec=ToolUseBlock)
            block.name = name
            block.input = {}
            blocks.append(block)
    else:
        block = MagicMock(spec=TextBlock)
        block.text = "thinking..."
        blocks.append(block)
    msg.content = blocks
    return msg
```

- [ ] **Step 3: Run all tests**

Run: `pytest tests/test_runner.py -v`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add src/a2sdlc/runner.py tests/test_runner.py
git commit -m "feat: update run_stage to use ProgressState, add branch param"
```

---

### Task 6: Update StageRunner protocol and FakeRunner

**Files:**
- Modify: `src/a2sdlc/adapters/protocols.py:59-72`
- Modify: `tests/fakes.py:141-186`
- Test: `tests/test_dispatch.py`

- [ ] **Step 1: Update StageRunner protocol**

In `src/a2sdlc/adapters/protocols.py`, add `branch` to `StageRunner.run()`:

```python
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
        branch: str = "",
    ) -> RunResult: ...
```

- [ ] **Step 2: Update FakeRunner**

In `tests/fakes.py`, update `_RunnerCall` and `FakeRunner.run()`:

```python
@dataclass
class _RunnerCall:
    user_prompt: str
    system_prompt: str
    config: StageConfig
    ticket_key: str
    stage: StageName
    project_root: str
    is_resume: bool
    on_progress: Callable[[str], None] | None
    branch: str


class FakeRunner:
    """In-memory StageRunner for tests. Returns canned result."""

    def __init__(self, result: RunResult) -> None:
        self._result = result
        self.calls: list[_RunnerCall] = []

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
        branch: str = "",
    ) -> RunResult:
        self.calls.append(
            _RunnerCall(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                config=config,
                ticket_key=ticket_key,
                stage=stage,
                project_root=project_root,
                is_resume=is_resume,
                on_progress=on_progress,
                branch=branch,
            )
        )
        return self._result
```

- [ ] **Step 3: Run dispatch tests to verify nothing breaks**

Run: `pytest tests/test_dispatch.py -v`
Expected: All PASS. Dispatch doesn't pass `branch` yet (that's Task 7), but the default `branch=""` keeps everything compatible.

- [ ] **Step 4: Commit**

```bash
git add src/a2sdlc/adapters/protocols.py tests/fakes.py
git commit -m "feat: add branch param to StageRunner protocol and FakeRunner"
```

---

### Task 7: Update dispatch.py to use new formatters and pass branch

**Files:**
- Modify: `src/a2sdlc/dispatch.py`
- Test: `tests/test_dispatch.py`

- [ ] **Step 1: Write test for branch being passed to runner**

Add to `tests/test_dispatch.py`:

```python
@pytest.mark.unit
class TestDispatchBranchPassing:
    @pytest.mark.asyncio
    async def test_passes_branch_to_runner(self) -> None:
        """Dispatch passes the git branch name to the runner."""
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.SPEC),
            result=_success_result("complete"),
        )
        await dispatch(h.ctx)

        assert len(h.runner.calls) == 1
        assert h.runner.calls[0].branch == "a2sdlc/T-1"
```

- [ ] **Step 2: Write test for new status bar in final comment**

Add to `tests/test_dispatch.py`:

```python
@pytest.mark.unit
class TestDispatchStatusBar:
    @pytest.mark.asyncio
    async def test_final_comment_has_status_bar(self) -> None:
        """Final comment should contain a markdown table status bar."""
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.SPEC),
            result=_success_result("complete"),
        )
        await dispatch(h.ctx)

        # Last updated comment is the final one
        final_body = h.tickets.updated_comments[-1][2]
        assert "| Model |" in final_body
        assert "claude-sonnet-4-6" in final_body

    @pytest.mark.asyncio
    async def test_error_comment_has_status_bar(self) -> None:
        """Error comment should contain a status bar."""
        h = _make(
            event=DispatchInput(key="T-1", stage=StageName.SPEC),
            result=_failure_result("timeout (60min)"),
        )
        await dispatch(h.ctx)

        final_body = h.tickets.updated_comments[-1][2]
        assert "🚨" in final_body
        assert "| Model |" in final_body
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_dispatch.py::TestDispatchBranchPassing tests/test_dispatch.py::TestDispatchStatusBar -v`
Expected: FAIL — branch not passed yet, old format_cost still used.

- [ ] **Step 4: Update dispatch.py**

In `src/a2sdlc/dispatch.py`, update the import:

```python
from a2sdlc.runner import format_error, format_final
```

Remove the `from a2sdlc.runner import format_cost` import.

Update step 10 (runner call) — pass `branch`:

Replace:
```python
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
```

With:
```python
    result = await ctx.runner.run(
        user_prompt=ticket_context,
        system_prompt=system_prompt,
        config=stage_config,
        ticket_key=event.key,
        stage=event.stage,
        project_root=str(ctx.project_root),
        is_resume=event.is_resume,
        on_progress=on_progress,
        branch=branch,
    )
```

Update step 11 — replace `format_cost` usage. The `cost_footer` variable and its usage in the success path, error path, and no-status-block path all need updating.

Replace the block from `# 11. Log full output` through the error handling and success comment:

```python
    # 11. Log full output to CI (always, regardless of success)
    print(f"::group::Agent output ({len(result.output)} chars)")  # noqa: T201
    print(result.output)  # noqa: T201
    print("::endgroup::")  # noqa: T201

    # Common format args for status bar
    milestones = result.progress.milestones if result.progress else []
    fmt_kwargs = dict(
        milestones=milestones,
        model=stage_config.model,
        branch=branch,
        max_turns=stage_config.max_turns,
        context_window=result.progress.context_window if result.progress else None,
    )

    # 11a. Always commit+push agent work (even on failure — preserves session/files)
    def _commit_and_push() -> None:
        try:
            ctx.git.commit_artifacts("chore: stage artifacts", [".a2sdlc/", "docs/"])
            ctx.git.push()
        except Exception:  # noqa: BLE001
            ctx.logger.warning("dispatch.commit_push_failed", exc_info=True)

    if not result.success:
        error_comment = format_error(result, **fmt_kwargs)
        ctx.tickets.update_comment(event.key, comment_id, error_comment)
        _commit_and_push()
        ctx.tickets.set_blocked(event.key, result.error or "unknown")
        return DispatchResult(stage=event.stage, blocked=True, error=result.error)

    # 12. Parse result
    stage_result = extract_result(result.output)
    if stage_result is None:
        partial = result.output[:2000]
        error_msg = (
            f"⚠️ No status block in **{event.stage.value}** output."
            f"\n\n{partial}\n\n{format_final(result, **fmt_kwargs)}"
        )
        ctx.tickets.update_comment(event.key, comment_id, error_msg)
        _commit_and_push()
        ctx.tickets.set_blocked(event.key, "no status block in output")
        return DispatchResult(stage=event.stage, blocked=True, error="no_status_block")

    comment_body = strip_status_block(result.output)
    final_comment = format_final(
        RunResult(
            success=result.success,
            output=comment_body,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_cost_usd=result.total_cost_usd,
            duration_ms=result.duration_ms,
            num_turns=result.num_turns,
        ),
        **fmt_kwargs,
    )
    ctx.tickets.update_comment(event.key, comment_id, final_comment)
```

- [ ] **Step 5: Run all dispatch tests**

Run: `pytest tests/test_dispatch.py -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add src/a2sdlc/dispatch.py tests/test_dispatch.py
git commit -m "feat: dispatch uses status bar formatters, passes branch to runner"
```

---

### Task 8: Remove old format_cost, update remaining references, run full check

**Files:**
- Modify: `src/a2sdlc/runner.py` (remove `format_cost`)
- Modify: `tests/test_runner.py` (remove `TestFormatCost`)
- Test: full suite

- [ ] **Step 1: Check for remaining references to format_cost**

Run: `grep -r "format_cost" src/ tests/`

If any references remain in dispatch.py or elsewhere, they need updating. The dispatch.py import was already changed in Task 7.

- [ ] **Step 2: Remove format_cost from runner.py**

Delete the `format_cost` function from `src/a2sdlc/runner.py`.

- [ ] **Step 3: Remove TestFormatCost from tests**

Delete the `TestFormatCost` class from `tests/test_runner.py`. Also remove `format_cost` from the import line.

- [ ] **Step 4: Run the full quality gate**

Run: `make check`
Expected: All checks pass — lint, tests, coverage, security.

- [ ] **Step 5: Commit**

```bash
git add src/a2sdlc/runner.py tests/test_runner.py
git commit -m "chore: remove old format_cost, replaced by format_final"
```

---

### Task 9: Verify end-to-end rendering

This is a manual verification task — no code changes, just confirming the output looks right.

- [ ] **Step 1: Run the full test suite one final time**

Run: `make check`
Expected: All green.

- [ ] **Step 2: Visually inspect format output**

Add a temporary script or use a Python REPL to render sample output and verify markdown looks correct:

```python
from a2sdlc.runner import (
    Milestone,
    ProgressState,
    RunResult,
    ToolEntry,
    format_error,
    format_final,
    format_progress,
)

# In-progress
ps = ProgressState(
    model="claude-sonnet-4-6",
    branch="feat/T-42",
    max_turns=120,
    context_window=200_000,
    project_root="/tmp/test",
    start_time=0.0,
    input_tokens=45000,
    output_tokens=12000,
    total_cost_usd=0.72,
    num_turns=12,
)
ps.tool_log = [
    ToolEntry(timestamp=float(i * 10), name="Read", target=f"src/file{i}.py")
    for i in range(15)
]
ps.milestones = [
    Milestone(timestamp=42.0, label="brainstorming invoked"),
    Milestone(timestamp=135.0, label="writing-plans invoked"),
]
print(format_progress("implement", ps, elapsed=135.0))
print("\n" + "=" * 60 + "\n")

# Final
result = RunResult(
    success=True,
    output="Implementation complete. All tests pass.",
    input_tokens=312000,
    output_tokens=24000,
    total_cost_usd=2.14,
    duration_ms=522000,
    num_turns=45,
)
print(
    format_final(
        result,
        milestones=ps.milestones,
        model="claude-sonnet-4-6",
        branch="feat/T-42",
        max_turns=120,
        context_window=200_000,
    )
)
```

Verify the markdown renders correctly — paste into a GitHub issue preview if possible.

- [ ] **Step 3: Done**

All tasks complete. The progress status bar is implemented.
