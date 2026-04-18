# Spec: Progress Subscribers — One Event Stream, N Consumers

**Date:** 2026-04-18
**Branch:** `feat/local-runner`
**Status:** Revised after code review (round 1)

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

Frozen dataclasses, one per concrete event type, all members of a `ProgressEvent` union:

```python
# evaluation/progress.py

@dataclass(frozen=True)
class StageStart:
    stage: StageName
    session_id: str
    started_at: float          # time.monotonic()

@dataclass(frozen=True)
class ToolCall:
    name: str                  # "Read", "Bash", "Skill", ...
    target: str                # extract_target(...) result
    timestamp: float           # elapsed seconds since stage start

@dataclass(frozen=True)
class GroupOpen:
    title: str

@dataclass(frozen=True)
class GroupClose:
    pass

@dataclass(frozen=True)
class Metrics:
    input_tokens: int
    output_tokens: int
    total_cost_usd: float
    num_turns: int
    elapsed: float             # seconds since stage_start, monotonic clock

@dataclass(frozen=True)
class Milestone:
    label: str                 # "brainstorming invoked", "spec approved"
    timestamp: float

@dataclass(frozen=True)
class StageEnd:
    stage: StageName
    success: bool
    error: str | None
    final_metrics: Metrics

ProgressEvent = StageStart | ToolCall | GroupOpen | GroupClose | Metrics | Milestone | StageEnd
```

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

`ProgressState` keeps its existing fields (tokens, cost, tool_log, milestones, etc.) and gains a subscriber registry plus mutation methods that emit events:

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

    async def stage_start(self, stage: StageName, session_id: str) -> None:
        self._failed.clear()  # fresh per-stage
        self.start_time = time.monotonic()
        await self._emit(StageStart(stage, session_id, self.start_time))

    async def add_tool_call(self, name: str, target: str) -> None:
        elapsed = time.monotonic() - self.start_time
        self.tool_log.append(ToolEntry(timestamp=elapsed, name=name, target=target))
        await self._emit(ToolCall(name=name, target=target, timestamp=elapsed))

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
```

**Clock discipline.** `ProgressState.start_time` switches from `time.time()` (wall clock, today) to `time.monotonic()`. All `elapsed` values and the `Throttle` utility use `time.monotonic()` consistently. Wall-clock timestamps are only meaningful for log records emitted by Python's `logging` module, which already handles them.

The runner stops calling `progress_adapter.on_*` and stops accepting `on_progress`. It only `await`s these mutation methods. `cli_local.py:196`'s direct call to `progress.on_stage_start(stage, session_id)` on the adapter is removed; the runner now invokes `progress_state.stage_start(...)` itself at the top of `run_stage`.

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
    def __init__(self, comment_handle, throttle_seconds: float = 5.0):
        self._comment = comment_handle
        self._throttle = Throttle(min_interval=throttle_seconds)
        self._stage: StageName | None = None
        self._state_ref: ProgressState | None = None  # cached on StageStart

    async def handle(self, event):
        if isinstance(event, StageStart):
            self._stage = event.stage
        elif isinstance(event, Metrics) and self._throttle.ready():
            text = format_progress(self._stage, self._state_ref)
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

(The `state_ref` caching shows one approach; a cleaner alternative is to pass the state into the constructor at composition time. Plan-time decision.)

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

Dispatch composition root:

```python
# pipeline/dispatch.py
ctx.progress_state.subscribe(GhActionsLogSubscriber())
ctx.progress_state.subscribe(GhCommentSubscriber(comment, ctx.progress_state))
```

```python
# cli_local.py
ctx.progress_state.subscribe(ConsoleSubscriber(ctx.progress_state))
```

Tests:

```python
recorder = RecordingSubscriber()
ctx.progress_state.subscribe(recorder)
# ... run stage ...
assert isinstance(recorder.events[0], StageStart)
assert any(isinstance(e, ToolCall) and e.name == "Skill" for e in recorder.events)
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

1. Add `ProgressEvent` taxonomy + mutation methods to `evaluation/progress.py`.
2. Add `Throttle` to `evaluation/throttle.py`.
3. Add `Subscriber` Protocol to `adapters/protocols.py`.
4. Add `RecordingSubscriber` in `tests/fakes.py`.
5. Rewrite `ConsoleProgressAdapter` → `ConsoleSubscriber`. Rename file. Same surface (rich.Live), now driven by events.
6. Rewrite `GhActionsProgressAdapter` → `GhActionsLogSubscriber`. Rename file. Same `::group::` markers.
7. Add `GhCommentSubscriber` (new file). Move the lambda logic from `dispatch.py:252` into it.
8. Update `pipeline/runner.py`: drop `on_progress` kwarg, drop direct `progress_adapter.on_*` calls, `await` `ProgressState` mutation methods instead.
9. Delete `ProgressAdapter` Protocol from `adapters/protocols.py`.
10. Update `dispatch.py` and `cli_local.py` to register subscribers instead of constructing a single adapter.
11. Rewrite tests that mocked `ProgressAdapter` — switch to `RecordingSubscriber`.

---

## 6. Testing

- **Unit (`evaluation/`):** `ProgressState` emits the right events at the right time. Order across `subscribe()` calls. Subscriber-raises-exception is contained, the failing subscriber is added to `_failed`, subsequent emits skip it, and `stage_start()` clears the set. `Throttle` admits the first call and rejects within-window subsequent calls.
- **Per subscriber:** `RecordingSubscriber` captures everything; concrete subscribers (`ConsoleSubscriber`, `GhActionsLogSubscriber`, `GhCommentSubscriber`) tested in isolation against synthetic event sequences with a fake comment handle.
- **Integration:** existing fake-runner SPEC→IMPLEMENT test gains a `RecordingSubscriber` to assert the event sequence (`StageStart → ToolCall* → Metrics* → StageEnd`), and to assert that `StageEnd` arrives after the final `Metrics` event — locking the terminal-state guarantee from §3.6.
- **Smoke:** the existing `a2sdlc-smoke` workspace re-runs SPEC + IMPLEMENT; status bar must show real numbers; GitHub-flow path is **not** smoke-tested locally (no GH token in smoke), but `GhCommentSubscriber` gets a unit test using a fake comment handle.

---

## 7. Risks & Trade-offs

| Risk | Mitigation |
|---|---|
| ProgressState gains behavior (stops being a pure dataclass) | Keep behavior narrow: only `subscribe`, mutation methods, `_emit`. No business logic. |
| Subscriber list mutated mid-stage | List is snapshotted on each `_emit` (§3.7). Late `subscribe()` calls take effect on the next event. No raise, no surprise. |
| Event taxonomy churn (adding/renaming events later) | Tagged union with explicit names; subscribers ignore unknown types via `isinstance` filter — additive changes are safe. |
| Async `handle` adds latency for sync subscribers | Defining `async def handle` with no `await` body is zero-overhead in CPython's asyncio (the coroutine resolves on first `await`-by-caller). The latency cost is real only for genuinely-async subscribers, which is exactly when you want it. |
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
- `git grep -E "time\\.(monotonic|time)\\(\\).*throttle|throttle.*time\\." src/a2sdlc/pipeline/` returns no matches — no time-based throttle exists in the runner or dispatch packages. The only `Throttle` instantiations live in `src/a2sdlc/adapters/`.
- `RecordingSubscriber`-based integration test asserts `StageEnd` appears after the final `Metrics` for a representative SPEC stage run.
- All migration steps (§5) land in a single PR; no intermediate commit is expected to pass `make check`. The PR description states this explicitly.
