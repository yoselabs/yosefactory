# Progress Status Bar & Transparency Redesign

**Date:** 2026-04-05
**Scope:** Cluster 1 (progress comment content), Cluster 4 (status bar), item 12 (skill invocation persistence)

## Problem

During stage execution, the GitHub issue comment shows a flat list of tool names with no context — no model, no token usage, no cost, no turn count, no timestamps, no skill invocations. The final comment has a basic cost footer but loses all execution context. There's no consistent "status bar" across in-progress and final states.

## Design

### ProgressState dataclass

New dataclass in `runner.py` that accumulates metrics during streaming:

```python
@dataclass
class ToolEntry:
    """Single tool call with context."""
    timestamp: float       # seconds since stage start
    name: str              # tool name (Read, Edit, Bash, etc.)
    target: str            # extracted target (file path, command preview, pattern)

@dataclass
class Milestone:
    """Persistent event that survives comment overwrites."""
    timestamp: float       # seconds since stage start
    label: str             # e.g. "brainstorming invoked"

@dataclass
class ProgressState:
    """Accumulated metrics during stage execution."""
    model: str
    branch: str
    max_turns: int
    context_window: int         # total context window size in tokens

    start_time: float           # time.time() at stage start
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_usd: float = 0.0
    num_turns: int = 0
    tool_log: list[ToolEntry] = field(default_factory=list)
    milestones: list[Milestone] = field(default_factory=list)
```

### Token/cost accumulation

On each `AssistantMessage` during streaming, accumulate usage:

```python
if isinstance(msg, AssistantMessage):
    usage = getattr(msg, "usage", None)
    if usage:
        progress.input_tokens = _get_tokens(usage, "input_tokens")
        progress.output_tokens = _get_tokens(usage, "output_tokens")
    cost = getattr(msg, "total_cost_usd", None)
    if cost:
        progress.total_cost_usd = cost
```

Note: SDK `AssistantMessage.usage` reports cumulative totals (not deltas), so we overwrite rather than sum. If it turns out to be deltas, switch to `+=`. Verify empirically on first run.

### Context window size

Map model names to context window sizes. Start with a simple dict:

```python
_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-sonnet-4-6": 200_000,
    "claude-opus-4-6": 1_000_000,
    "claude-haiku-4-5-20251001": 200_000,
}
```

Context fill % = `input_tokens / context_window * 100`. If model not in map, omit the percentage.

### Tool target extraction

Extract meaningful targets from tool inputs instead of just the tool name:

```python
def _extract_target(name: str, inp: dict) -> str:
    if name in ("Read", "Glob", "Grep"):
        path = inp.get("file_path") or inp.get("path") or inp.get("pattern", "")
        return _shorten_path(path)
    if name == "Edit":
        path = inp.get("file_path", "")
        # No line number available in Edit input, just show path
        return _shorten_path(path)
    if name == "Bash":
        cmd = inp.get("command", "")
        return f"`{cmd[:60]}`"
    if name == "Write":
        return _shorten_path(inp.get("file_path", ""))
    if name == "Skill":
        return inp.get("skill", "")
    return ""
```

`_shorten_path`: strip common prefixes (project root) to keep paths readable.

### Skill invocation detection

When a tool call is `Skill` (or matches known skill patterns), record it as a `Milestone`:

```python
if name == "Skill":
    skill_name = inp.get("skill", "unknown")
    progress.milestones.append(Milestone(
        timestamp=elapsed,
        label=f"{skill_name} invoked",
    ))
```

### Turn counting

Increment `progress.num_turns` on each `AssistantMessage`. The SDK's `ResultMessage.num_turns` gives the final count, but we need it live during streaming.

### Rendering: format_progress (in-progress)

```
⏳ **{stage}** in progress...

| Model | Branch | Context | Cost | Tokens | Duration | Turns |
|-------|--------|---------|------|--------|----------|-------|
| {model} | {branch} | {input_tokens_k}k/{window_k}k ({pct}%) | ${cost} | {in_k}k in / {out_k}k out | {duration} | {turns}/{max_turns} |

📌 0:42 — brainstorming invoked
📌 2:15 — writing-plans invoked

| Time | Tool | Target |
|------|------|--------|
| ... |  | *(N earlier)* |
| 3:01 | Read | src/app.py |
| 3:12 | Edit | src/app.py |
| 3:28 | Bash | `pytest tests/` |
```

- Show last 10 tool entries in the table
- If more than 10, first row shows count of earlier entries
- Milestones section only appears if there are milestones
- Duration formatted as `Xs`, `Xm Ys`, or `Xh Ym`

### Rendering: format_final (completion)

```
{agent_response_body}

---

| Model | Branch | Context | Cost | Tokens | Duration | Turns |
|-------|--------|---------|------|--------|----------|-------|
| {model} | {branch} | {final_tokens}k/{window}k ({pct}%) | ${cost} | {in}k in / {out}k out | {duration} | {turns}/{max} |

📌 0:42 — brainstorming invoked
📌 2:15 — writing-plans invoked
📌 6:30 — requesting-code-review invoked
```

- Status bar uses final values from `ResultMessage` (authoritative)
- Milestones persist
- Tool log is dropped (agent response replaces it)
- This replaces the current `format_cost()` function

### Rendering: format_error (failure)

```
🚨 **{stage}** failed: `{error}`

---

| Model | Branch | Context | Cost | Tokens | Duration | Turns |
|-------|--------|---------|------|--------|----------|-------|
| ... |

📌 milestones if any
```

Same status bar, just with error header instead of agent response.

### Integration with dispatch.py

Changes to dispatch:

1. **Pass branch name and model to runner** — runner needs these for ProgressState. Add `branch` param to `run_stage()`. Model already available via `config.model`.

2. **Replace `format_cost()`** — dispatch currently calls `format_cost(result)` for the footer. Replace with `format_final(result, progress_state)` which renders the full status bar + milestones.

3. **on_progress callback** — already in place, just receives the new format.

4. **Error path** — use `format_error(result, progress_state)` instead of inline string building.

### Integration with runner.py

Changes to `run_stage()`:

1. Create `ProgressState` at start with model, branch, max_turns, context_window.
2. In streaming loop, on each `AssistantMessage`:
   - Accumulate tokens/cost from usage
   - Increment turn count
   - Extract tool entries with targets and timestamps
   - Detect skill invocations → milestones
3. `on_progress` calls `format_progress(stage, progress_state)` instead of the old signature.
4. Return `ProgressState` alongside `RunResult` (or attach it to RunResult).

### RunResult changes

Add `progress` field to `RunResult`:

```python
@dataclass
class RunResult:
    # ... existing fields ...
    progress: ProgressState | None = None
```

This lets dispatch access milestones and status bar data for the final comment without re-deriving it.

## Files changed

| File | Change |
|------|--------|
| `src/a2sdlc/runner.py` | Add ProgressState, ToolEntry, Milestone dataclasses. Rewrite `format_progress()`. Add `format_final()`, `format_error()`. Update `_handle_assistant_message()` to populate ProgressState. Update `run_stage()` signature (add branch param). |
| `src/a2sdlc/dispatch.py` | Pass branch to runner. Replace `format_cost()` usage with `format_final()`/`format_error()`. |
| `src/a2sdlc/config.py` | Add `_CONTEXT_WINDOWS` dict. |
| `tests/` | Update existing runner/dispatch tests for new signatures. Add tests for format_progress, format_final, tool target extraction. |

## Out of scope

- Milestone sections / collapsible logs (Cluster 3) — future work
- Timer-based updates decoupled from tool activity (item 10) — current 5s throttle is adequate
- Turn exhaustion → stage:blocked (item 16) — pipeline logic, not display
- Table format for CI/GH Actions logs — only affects the issue comment format
