# Spec: Progress Subscribers — One Event Stream, N Consumers

**Date:** 2026-04-18
**Branch:** `feat/local-runner`
**Status:** Revised after code review (round 2)

---

## 1. Problem

The pipeline runner today pushes the same underlying progress data through **two unrelated channels**:

- `ProgressAdapter` protocol (`adapters/protocols.py`) with five method calls (`on_event`, `on_group_open`, `on_group_close`, `on_stage_start`, `on_stage_end`). Each deployment uses exactly one implementation: `ConsoleProgressAdapter` (local CLI) or `GhActionsProgressAdapter` (GH dispatch).
- An ad-hoc `on_progress: Callable[[str], None]` keyword on the runner — wired in `pipeline/dispatch.py:252` to a lambda that edits the GitHub issue/PR comment every 5 seconds. Only the GH dispatch path uses it.

So today's surface is **two single-adapter deployments plus one piggybacked callback in dispatch**. Same data, two parallel transport mechanisms.

This caused two concrete defects already:

1. **Console status bar shows `0/0 / $0.00 / 0 turns` throughout every local run.** `ConsoleProgressAdapter` defines `update_metrics()` but no caller exists. Real numbers only land in MLflow and the post-run summary.
2. **Throttling is hardcoded in the runner.** The 5-second cadence in `runner.py:128` serves the GitHub-comment subscriber's API-rate concern but over-throttles the local console (which would happily redraw every tick) and is invisible to any future subscriber that wants different pacing (MLflow live, Slack notifier, structured-log file).

The smell will compound: the `eval-system` work and the `agentic-web-stack` template both have live-observability requirements that mean adding a third or fourth surface within the next quarter.

---

## 2. Goal

Replace the two parallel channels with **one typed event stream** flowing from the runner through `ProgressState` to N independent subscribers. Eliminate `on_progress`, dissolve `ProgressAdapter`, and move throttling into the subscribers that need it.

Non-goals:

- Backpressure / retry logic for failing subscribers (out of scope; subscriber implementation choice).
- Persistence or replay of the event stream.
- Cross-stage event correlation beyond what `ProgressState` already provides.

---

## 3. Design

### 3.1 Event taxonomy

Dataclasses in `evaluation/progress.py`. **Existing `ToolEntry` (line 12) and `Milestone` (line 21) classes are reused as event types** — they already carry `(timestamp, name, target)` and `(timestamp, label)` respectively, are appended to `ProgressState.tool_log` / `ProgressState.milestones` today, and naturally double as the events emitted at append-time. New event classes are added alongside:

```python
# evaluation/progress.py

# Reused as-is (already defined):
#   class ToolEntry: timestamp: float; name: str; target: str
#   class Milestone: timestamp: float; label: str

@dataclass
class StageStart:
    stage: StageName
    session_id: str
    started_at: float          # time.monotonic()

@dataclass
class GroupOpen:
    title: str

@dataclass
class GroupClose:
    pass

@dataclass
class Metrics:
    input_tokens: int
    output_tokens: int
    total_cost_usd: float
    num_turns: int
    elapsed: float             # seconds since stage_start, monotonic clock

@dataclass
class StageEnd:
    stage: StageName
    success: bool
    error: str | None
    final_metrics: Metrics

ProgressEvent = StageStart | ToolEntry | GroupOpen | GroupClose | Metrics | Milestone | StageEnd
```

(Events are not declared `frozen=True` — matching the existing `ToolEntry`/`Milestone` style. Subscribers should treat events as immutable by convention; no runtime guard.)

**No `StatusText` event.** Subscribers that want a rendered one-liner (the GH-comment use case) import `format_progress(stage, ProgressState)` and render it themselves on `Metrics`. Reasons: emitting a pre-rendered string would (a) force every subscriber to pay the format cost on every metrics tick even if no one wants the text, (b) lock the rendering cadence to `Metrics`, removing the throttle freedom this refactor sells, and (c) mean two events for one logical change. Each subscriber decides whether to render and at what cadence.

A consequence: `ProgressState` does not need `stage_name` or `session_id` fields. Subscribers that need stage context cache it from `StageStart` in their own state.

### 3.2 Subscriber interface

```python
# adapters/protocols.py  (alongside WorkAdapter, GitAdapter, ReviewAdapter, StageRunner)

class Subscriber(Protocol):
    async def handle(self, event: ProgressEvent) -> None: ...
```

`Subscriber` lives in `adapters/protocols.py` for consistency with every other port in this codebase — `WorkAdapter`, `GitAdapter`, `ReviewAdapter`, `StageRunner` all live there. The event taxonomy itself stays in `evaluation/progress.py` because the events are progress-domain vocabulary, but the *port* (the consumer interface) is a platform abstraction and belongs with the other ports.

**`handle` is `async`.** The runner is already async (`runner.py:119` is `async def _stream`). Defining `handle` as `async def` and `await`ing it costs one keyword and zero new failure modes, while keeping the door open for subscribers that genuinely need I/O — Slack webhooks (`httpx.post` is 200–2000 ms), authenticated REST calls, etc. The alternative ("sync now, spawn-and-forget if you need async later") creates unawaited-task bugs (exceptions vanish, ordering breaks) and pushes complexity into every async subscriber. Sync subscribers just `async def handle(self, event): ...` with no `await` — same code shape, no overhead.

### 3.3 ProgressState becomes the bus

**Lifecycle change:** today `ProgressState` is constructed inside `runner.run_stage` (per stage). After this refactor it is **constructed once per dispatch lifetime in the composition root** (`cli_local.py` for local runs, `cli.py`/`pipeline/dispatch.py` for GH dispatch) and reused across stages — so subscribers register on it before any stage starts. `stage_start()` is the per-stage refresh point; the subscriber list survives across stages.

**Field partition:**

| Field | Lifetime | Set in |
|---|---|---|
| `project_root` | dispatch | `__init__` |
| `_subscribers`, `_failed` | dispatch (subscriber list); per-stage (failed set, cleared in `stage_start`) | `__init__` / mutated by `subscribe`, `stage_start`, `_emit` |
| `model`, `max_turns`, `context_window` | **per-stage** (each stage uses its own `StageConfig`) | refreshed in `stage_start` from the passed `StageConfig` |
| `branch` | per-stage in principle (could change across stages); set in `stage_start` | `stage_start` |
| `start_time` | per-stage | `stage_start` |
| `tool_log`, `milestones`, `tasks` | per-stage (cleared on `stage_start`) | mutated by `add_tool_call`, `add_milestone`, etc. |
| `input_tokens`, `output_tokens`, `total_cost_usd`, `num_turns` | per-stage (reset to 0 on `stage_start`) | mutated by `update_metrics` |

`ProgressState.__init__` therefore takes only `project_root`. Per-stage values are passed to `stage_start()` and overwrite the previous stage's values. This avoids the bug where SPEC's model/max_turns would leak into IMPLEMENT's status bar.

`DispatchContext.progress` (today: `ProgressAdapter`) is renamed to `DispatchContext.progress_state: ProgressState`. The `RunResult.progress` field still returns the same live `ProgressState` reference — its fields all survive intact; only the lifecycle changes from per-stage to per-dispatch. **Callers that read per-stage data off `RunResult.progress` (e.g. `tool_log`, `milestones`) must consume it before the next `stage_start()` clears it, or snapshot it.** Today's only such caller is `pipeline/stage_executor.py:_milestones`, which already snapshots immediately after the stage returns — safe.

`ProgressState` gains a subscriber registry plus mutation methods that emit events:

```python
class ProgressState:
    # ... existing fields ...
    _subscribers: list[Subscriber] = field(default_factory=list, init=False)
    _failed: set[int] = field(default_factory=set, init=False)  # id(subscriber) → skip

    def subscribe(self, sub: Subscriber) -> None:
        self._subscribers.append(sub)

    async def _emit(self, event: ProgressEvent) -> None:
        # Snapshot the list so a subscriber registering or being skipped mid-emit
        # doesn't perturb iteration. Cheap (list copy of ≤ ~5 items per stage).
        for sub in list(self._subscribers):
            if id(sub) in self._failed:
                continue
            try:
                await sub.handle(event)
            except Exception:
                logging.getLogger("a2sdlc.progress").exception(
                    "Subscriber %s failed; skipping for remainder of stage",
                    type(sub).__name__,
                )
                self._failed.add(id(sub))

    async def stage_start(
        self,
        stage: StageName,
        session_id: str,
        *,
        model: str,
        max_turns: int,
        context_window: int,
        branch: str,
    ) -> None:
        # Refresh per-stage configuration (each stage may use its own StageConfig).
        self.model = model
        self.max_turns = max_turns
        self.context_window = context_window
        self.branch = branch
        # Reset per-stage mutable state; subscriber list and project_root survive.
        self._failed.clear()
        self.tool_log.clear()
        self.milestones.clear()
        self.tasks.clear()
        self.input_tokens = self.output_tokens = self.num_turns = 0
        self.total_cost_usd = 0.0
        self.start_time = time.monotonic()
        await self._emit(StageStart(stage, session_id, self.start_time))

    async def add_tool_call(self, name: str, target: str) -> None:
        elapsed = time.monotonic() - self.start_time
        entry = ToolEntry(timestamp=elapsed, name=name, target=target)
        self.tool_log.append(entry)
        await self._emit(entry)

    async def update_metrics(self, tin: int, tout: int, cost: float, turns: int) -> None:
        self.input_tokens, self.output_tokens = tin, tout
        self.total_cost_usd, self.num_turns = cost, turns
        elapsed = time.monotonic() - self.start_time
        await self._emit(Metrics(tin, tout, cost, turns, elapsed))

    async def open_group(self, title: str) -> None: ...
    async def close_group(self) -> None: ...
    async def add_milestone(self, label: str) -> None: ...
    async def stage_end(self, success: bool, error: str | None,
                        final: Metrics) -> None: ...

    def snapshot_metrics(self) -> Metrics:
        """Build a Metrics event from the current state — synchronous, no emit."""
        return Metrics(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            total_cost_usd=self.total_cost_usd,
            num_turns=self.num_turns,
            elapsed=time.monotonic() - self.start_time,
        )
```

**Clock discipline.** `ProgressState.start_time` switches from `time.time()` (wall clock, today) to `time.monotonic()`. All `elapsed` values and the `Throttle` utility use `time.monotonic()` consistently. Wall-clock timestamps are only meaningful for log records emitted by Python's `logging` module, which already handles them.

The runner stops calling `progress_adapter.on_*` and stops accepting `on_progress`. It only `await`s `progress_state.add_tool_call(...)`, `update_metrics(...)`, `add_milestone(...)`, `open_group(...)`, `close_group(...)`. It does **not** emit `StageStart`/`StageEnd` itself.

**`StageStart`/`StageEnd` are emitted by `pipeline/dispatch.py`**, not by the runner — wrapping every stage including ones that bypass `runner.run_stage` (notably MERGE, which returns from `dispatch()` without invoking the runner).

`dispatch.py` today has many early-return branches *before* the stage truly begins (feedback dedup, idempotency, circuit breaker, git BlockedError checks — all in lines 67-189). The natural insertion point is **immediately after `comment.start(target_stage.value)` at line 190**, which is where the stage is committed to running. The wrapper covers two sub-blocks:

1. **MERGE branch (today: lines 192-212)** — wrap with `stage_start(...)` / `stage_end(...)`. Uses MERGE's `StageConfig` for model/max_turns even though they're unused (load via `load_stage_config` for symmetry).
2. **SPEC/IMPLEMENT/REVIEW branch (today: lines 214-end)** — wrap from after `load_stage_config` (line 215, so we have `model`/`max_turns` for `stage_start`) through the executor call and post-processing.

Sketch (line numbers are pre-refactor):

```python
# dispatch.py, after line 190
stage_config = load_stage_config(target_stage.value, ctx.config)
await ctx.progress_state.stage_start(
    target_stage, session_id,
    model=stage_config.model,
    max_turns=stage_config.max_turns,
    context_window=context_window_for_model(stage_config.model) or 0,
    branch=branch,
)
try:
    if target_stage == StageName.MERGE:
        # existing MERGE logic (lines 192-212)
        ...
        await ctx.progress_state.stage_end(success=True, error=None, final=ctx.progress_state.snapshot_metrics())
        return DispatchResult(stage=StageName.MERGE)

    # existing prompt assembly + executor call (lines 217-end)
    exec_result = await executor.run(...)
    ...
    success = exec_result.success
    error = exec_result.error
finally:
    await ctx.progress_state.stage_end(success, error, ctx.progress_state.snapshot_metrics())
```

Early-return paths *before* `comment.start` (lines 67-189) do not emit stage events — those are routing decisions, not stage executions, and have no audience that cares.

Consequence: every executed stage produces `StageStart` + `StageEnd`. SDK-driven stages additionally produce `ToolEntry`, `Metrics`, `Milestone`, `GroupOpen`, `GroupClose` from inside the runner. MERGE produces only the bracket pair, which is correct: there is no agent activity to report.

### 3.4 Subscribers (replacing today's adapters)

| Today | After |
|---|---|
| `ConsoleProgressAdapter` (5 methods, broken status bar) | `ConsoleSubscriber.handle(event)` |
| `GhActionsProgressAdapter` (5 methods) | `GhActionsLogSubscriber.handle(event)` |
| Lambda in `dispatch.py:252` calling `comment.update(text)` | `GhCommentSubscriber.handle(event)` — proper class, owns its 5 s throttle |
| (none) | `RecordingSubscriber` — test helper, appends events to a list |

Each subscriber filters the events it cares about and drops the rest:

```python
class GhCommentSubscriber:
    def __init__(
        self,
        comment_handle,
        progress_state: ProgressState,
        throttle_seconds: float = 5.0,
    ):
        self._comment = comment_handle
        self._state = progress_state
        self._throttle = Throttle(min_interval=throttle_seconds)
        self._stage: StageName | None = None

    async def handle(self, event):
        if isinstance(event, StageStart):
            self._stage = event.stage
        elif isinstance(event, Metrics) and self._throttle.ready():
            text = format_progress(self._stage, self._state)
            await self._comment.update(text)
        elif isinstance(event, Milestone):
            await self._comment.append(f"✨ {event.label}")    # immediate, rare
        elif isinstance(event, StageEnd):
            icon = "✅" if event.success else "❌"
            await self._comment.finalize(
                f"{icon} {event.stage.value} done — "
                f"${event.final_metrics.total_cost_usd:.2f}, "
                f"{event.final_metrics.num_turns} turns"
            )
```

`progress_state` is constructor-injected at composition time — see §3.5. The subscriber doesn't need to cache it from `StageStart`; `_stage` is the only piece of per-stage context it tracks (and only because `format_progress` takes stage as a separate argument from state).

`Throttle` is a 10-line utility in **`evaluation/throttle.py`** (its own file — it has no progress semantics):

```python
class Throttle:
    def __init__(self, min_interval: float):
        self._min = min_interval
        self._last = 0.0
    def ready(self) -> bool:
        now = time.monotonic()
        if now - self._last < self._min: return False
        self._last = now
        return True
```

### 3.5 Composition (where subscribers get registered)

The composition root constructs `ProgressState` once and passes it into `DispatchContext`, then registers subscribers on it before invoking `dispatch()`.

GH dispatch composition root (`cli.py`):

```python
progress_state = ProgressState(model=config.model, branch=branch, ...)
progress_state.subscribe(GhActionsLogSubscriber())
progress_state.subscribe(GhCommentSubscriber(comment, progress_state))

ctx = DispatchContext(
    work=work_adapter,
    git=git,
    review=review_adapter,
    runner=SdkStageRunner(effort=config.effort),
    progress_state=progress_state,            # was: progress=progress_adapter
    config=config,
    project_root=project_root,
    logger=...,
)
```

Local runner (`cli_local.py`):

```python
progress_state = ProgressState(model=cfg.model, branch=branch_name, ...)
progress_state.subscribe(ConsoleSubscriber(progress_state))

ctx = DispatchContext(
    work=work, git=git, review=review,
    runner=runner,
    progress_state=progress_state,
    config=cfg,
    project_root=project_root,
    logger=...,
)
```

Tests:

```python
recorder = RecordingSubscriber()
ctx.progress_state.subscribe(recorder)
# ... run dispatch / run_stage ...
assert isinstance(recorder.events[0], StageStart)
assert any(isinstance(e, ToolEntry) and e.name == "Skill" for e in recorder.events)
assert isinstance(recorder.events[-1], StageEnd)
```

### 3.6 Terminal-state guarantee

`StageEnd` is emitted from `ProgressState.stage_end()` immediately after the runner receives the SDK's `ResultMessage`. It carries the authoritative final metrics from the result message (not a snapshot mid-stream), and it is **never throttled** — every subscriber receives it. This fixes a latent bug today where the 5 s throttle could swallow the very last `Metrics` update before the run ended, leaving the GitHub comment showing stale numbers until `finalize_comment` (called separately from `dispatch.py`) cleaned up.

### 3.7 Ordering and error containment

- Subscribers receive events in the order `subscribe()` was called.
- The subscriber list is **snapshotted on each `_emit` call** (a list copy of the current registry). Late `subscribe()` calls take effect on the next event; mid-emit registrations don't perturb the in-progress fan-out. No "raise on late subscribe" surprise.
- A subscriber raising an exception logs the failure (via `logging.getLogger("a2sdlc.progress")`) and is added to `ProgressState._failed: set[int]` keyed by `id(subscriber)`. Subsequent events skip it. The set is cleared at the start of each stage (`stage_start()`) so a transient failure doesn't permanently disable a subscriber across stages.
- One broken subscriber must not crash the run. Exceptions are caught at `_emit` boundaries, never propagated to the runner.
- `handle` is `async` (see 3.2). Subscribers are awaited sequentially in registration order. Event volume is low (≤ ~100 per stage); sequential `await` keeps ordering simple and exception attribution clean.

---

## 4. Layout

```
src/a2sdlc/
  evaluation/
    progress.py                  # ProgressState + ProgressEvent taxonomy
    throttle.py                  # Throttle utility (no progress semantics)
  adapters/
    protocols.py                 # + Subscriber Protocol (alongside existing ports)
    console_subscriber.py        # was progress_console.py
    gh_actions_subscriber.py     # was progress_gh_actions.py
    gh_comment_subscriber.py     # NEW
    factory.py                   # build_*_subscriber functions
  pipeline/
    runner.py                    # mutates ProgressState only; no on_progress kwarg
    dispatch.py                  # registers subscribers per deployment context
  cli_local.py                   # registers ConsoleSubscriber
tests/
  evaluation/test_progress_events.py   # event emission, ordering, exception containment
  evaluation/test_throttle.py
  adapters/test_*_subscriber.py        # one suite per subscriber
```

Hexagonal-lite invariant from `CLAUDE.md` holds: subscribers are I/O concerns → `adapters/`. Event taxonomy is progress-domain → `evaluation/`. The `Subscriber` *port* (consumer interface) lives in `adapters/protocols.py` for consistency with every other port. `domain/` stays untouched.

---

## 5. Migration

**Single PR. No compat shim. No intermediate commit is expected to pass `make check`.**

Rationale: there is one in-tree consumer of this code (the engine itself), the contract is internal, and the value of the refactor lives in the deletion of the old code. Partial deletion creates a worse state than either old or new. The PR description must call out the size; reviewers must read the full diff, not commit-by-commit.

Order:

1. Add `ProgressEvent` taxonomy + lifecycle/mutation methods to `evaluation/progress.py` (`subscribe`, `_emit`, `stage_start`, `stage_end`, `add_tool_call`, `update_metrics`, `add_milestone`, `open_group`, `close_group`, `snapshot_metrics`). Switch `start_time` to `time.monotonic()`. Repartition `__init__` to take only dispatch-lifetime fields (`project_root`); per-stage fields land via `stage_start`.
2. Add `Throttle` to `evaluation/throttle.py`.
3. Add `Subscriber` Protocol to `adapters/protocols.py` (alongside the existing ports).
4. Add `RecordingSubscriber` in `tests/fakes.py`.
5. Rewrite `ConsoleProgressAdapter` → `ConsoleSubscriber`. Rename file. Same surface (rich.Live), now driven by events.
6. Rewrite `GhActionsProgressAdapter` → `GhActionsLogSubscriber`. Rename file. Same `::group::` markers; this subscriber owns the `::group::Tool: <name>` output today emitted via `print(...)` in `runner.py:261-272` — the inline `print` fallback in `_handle_assistant_message` is removed and the subscriber reproduces it from `ToolEntry` events.
7. Add `GhCommentSubscriber` (new file). Move the lambda logic from `dispatch.py:252` into it. Constructor takes `(comment_handle, progress_state, throttle_seconds=5.0)`.
8. Update `pipeline/runner.py`: drop `on_progress` kwarg, drop direct `progress_adapter.on_*` calls, drop the inline `print("::group::...")` and `print("::endgroup::")` fallback in `_handle_assistant_message`. `await` `ProgressState` mutation methods instead. Runner does **not** emit `StageStart`/`StageEnd`.
9. **Rename `DispatchContext.progress: ProgressAdapter` → `DispatchContext.progress_state: ProgressState`.** Production call sites (line numbers pre-refactor):
   - `pipeline/dispatch.py:44` (field declaration)
   - `pipeline/dispatch.py:259-261` (`ctx.progress.on_group_open/on_event/on_group_close` — moves into `GhActionsLogSubscriber` reacting to `GroupOpen`/`GroupClose`/`ToolEntry` events)
   - `cli.py:139` (build the `progress` adapter), `cli.py:145-146` (pass into `DispatchContext` and `SdkStageRunner`)
   - `cli_local.py:99` (`SdkStageRunner(progress=...)`), `cli_local.py:172` (`build_progress_adapter`), `cli_local.py:174` (`_build_runner(progress, ...)`), `cli_local.py:190` (pass to `DispatchContext`), `cli_local.py:196` (delete `progress.on_stage_start`; dispatch now owns `StageStart` emission), `cli_local.py:266` (delete `progress.on_stage_end`; same).
   - Test fixtures: `tests/pipeline/test_dispatch.py` (4 occurrences), `tests/pipeline/test_dispatch_e2e.py` (2), `tests/pipeline/test_dispatch_progress.py` (1), `tests/pipeline/test_stage_executor.py` (2). Plus `tests/fakes.py` plumbing.
10. Update `pipeline/dispatch.py` to wrap the post-`comment.start` portion (line 190 onwards) with `await ctx.progress_state.stage_start(...)` / `stage_end(...)`, covering both the MERGE branch and the SPEC/IMPLEMENT/REVIEW branch. Pseudocode in §3.3.
11. Delete `ProgressAdapter` Protocol from `adapters/protocols.py`. Delete `SdkStageRunner.__init__`'s `progress: ProgressAdapter | None` parameter (`runner.py:287`).
12. **Extend `StageRunner.run` Protocol signature** (`adapters/protocols.py:27-38`) to accept `progress_state: ProgressState`. Thread the parameter through `StageExecutor.run` (`pipeline/stage_executor.py:44-70`, `:99-109`) and `run_stage` (`pipeline/runner.py:50-62`). The runner mutates this state instead of constructing its own. `RunResult.progress` returns this same reference.
13. Delete or rename `adapters/factory.build_progress_adapter` (`adapters/factory.py:61`). Likely repurposed as `build_console_subscriber` (no GH-side equivalent — GH composition wires its subscribers directly).
14. Update `cli.py` and `cli_local.py` to construct `ProgressState(project_root=...)` once at startup, register subscribers, and pass into `DispatchContext`. The runner no longer takes a progress adapter at construction; subscribers see all events via the shared `ProgressState`.
15. Rewrite tests that mocked `ProgressAdapter` — switch to `RecordingSubscriber`. Snapshot any per-stage data (`tool_log`, `milestones`) before the next `stage_start()` clears it.

---

## 6. Testing

- **Unit (`evaluation/`):** `ProgressState` emits the right events at the right time. Order across `subscribe()` calls. Subscriber-raises-exception is contained, the failing subscriber is added to `_failed`, subsequent emits skip it, and `stage_start()` clears the set. `Throttle` admits the first call and rejects within-window subsequent calls.
- **Per subscriber:** `RecordingSubscriber` captures everything; concrete subscribers (`ConsoleSubscriber`, `GhActionsLogSubscriber`, `GhCommentSubscriber`) tested in isolation against synthetic event sequences with a fake comment handle.
- **Integration:** existing fake-runner SPEC→IMPLEMENT test gains a `RecordingSubscriber` to assert the event sequence (`StageStart → ToolEntry* → Metrics* → StageEnd`), and to assert that `StageEnd` arrives after the final `Metrics` event — locking the terminal-state guarantee from §3.6.
- **Smoke:** the existing `a2sdlc-smoke` workspace re-runs SPEC + IMPLEMENT; status bar must show real numbers; GitHub-flow path is **not** smoke-tested locally (no GH token in smoke), but `GhCommentSubscriber` gets a unit test using a fake comment handle.

---

## 7. Risks & Trade-offs

| Risk | Mitigation |
|---|---|
| ProgressState gains behavior (stops being a pure dataclass) | Keep behavior narrow: only `subscribe`, mutation methods, `_emit`. No business logic. |
| Subscriber list mutated mid-stage | List is snapshotted on each `_emit` (§3.7). Late `subscribe()` calls take effect on the next event. No raise, no surprise. |
| Event taxonomy churn (adding/renaming events later) | Tagged union with explicit names; subscribers ignore unknown types via `isinstance` filter — additive changes are safe. |
| Async `handle` adds latency for sync subscribers | Per-emit overhead is microseconds (coroutine + frame allocation), negligible at the ≤ ~100 events/stage volume this bus carries. Cost is dominated by event construction itself. |
| Blocking I/O accidentally invoked from `async def handle` | Stalls the runner just as effectively as a slow async subscriber. Subscribers documented to use `httpx.AsyncClient`/`asyncio.to_thread` for any I/O. No runtime guard — caught in code review. |
| One slow async subscriber stalls the runner | Subscribers are awaited sequentially in registration order. A genuinely slow subscriber (e.g., Slack webhook) must own its own throttling and/or fire-and-forget pattern via `asyncio.create_task` inside its `handle`. Spec'd as the subscriber's responsibility, not the bus's. |
| Refactor scope larger than the symptom (status bar bug) | Acknowledged. Justified by the smell already producing two real defects, plus the imminent third-subscriber needs from `eval-system` and `agentic-web-stack`. |

---

## 8. Out of Scope

- Backpressure / queues / retry logic for failing subscribers.
- Persisting the event stream to disk for replay.
- Cross-stage event correlation (use MLflow parent runs).
- Restoring the agent-level filesystem fence (separate punch-list item).
- Threading `review_cycles` into `get_session_id` (separate punch-list item).
- A `kind: Literal[...]` discriminant on events for serialization (not needed until a subscriber wants JSON; `isinstance` dispatch is sufficient today).

---

## 9. Acceptance

- `pyright`, `ruff`, `pytest` all green.
- All existing 496 tests pass (after mock-replacement updates).
- Local smoke run shows non-zero tokens / cost / turns updating live in the console status bar.
- `git grep "ProgressAdapter" src/` returns no matches.
- `git grep "on_progress" src/` returns no matches.
- `git grep -nE "Throttle\\s*\\(" src/a2sdlc/pipeline/` returns no matches — no `Throttle` instances are constructed in `pipeline/`. All `Throttle()` instantiations live in `src/a2sdlc/adapters/`.
- `git grep -nE "time\\.(monotonic|time)\\(\\)" src/a2sdlc/pipeline/runner.py | grep -v start_time` returns no matches — no time-based pacing logic remains in the runner; only `start_time` capture in `ProgressState` interactions.
- `RecordingSubscriber`-based integration test asserts `StageEnd` appears after the final `Metrics` for a representative SPEC stage run.
- All migration steps (§5) land in a single PR; no intermediate commit is expected to pass `make check`. The PR description states this explicitly.
