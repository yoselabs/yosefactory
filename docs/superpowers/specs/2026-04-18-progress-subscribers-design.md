# Spec: Progress Subscribers — One Event Stream, N Consumers

**Date:** 2026-04-18
**Branch:** `feat/local-runner`
**Status:** Draft (awaiting code review)

---

## 1. Problem

The pipeline runner today pushes the same underlying progress data through **two unrelated channels**:

- `ProgressAdapter` protocol (`adapters/protocols.py`) with five method calls (`on_event`, `on_group_open`, `on_group_close`, `on_stage_start`, `on_stage_end`) — consumed by `ConsoleProgressAdapter` and `GhActionsProgressAdapter`.
- An ad-hoc `on_progress: Callable[[str], None]` keyword on the runner — wired in `pipeline/dispatch.py:252` to a lambda that edits the GitHub issue/PR comment every 5 seconds.

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

Frozen dataclasses, one per concrete event type, all subtypes of a `ProgressEvent` union:

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
    elapsed: float

@dataclass(frozen=True)
class Milestone:
    label: str                 # "brainstorming invoked", "spec approved"
    timestamp: float

@dataclass(frozen=True)
class StatusText:
    text: str                  # output of format_progress(stage, ProgressState)

@dataclass(frozen=True)
class StageEnd:
    stage: StageName
    success: bool
    error: str | None
    final_metrics: Metrics

ProgressEvent = StageStart | ToolCall | GroupOpen | GroupClose | Metrics | Milestone | StatusText | StageEnd
```

`StatusText` exists so subscribers that want a pre-formatted one-liner (the GitHub-comment use case) don't have to know how to format it themselves; it's emitted alongside `Metrics` from the same data.

### 3.2 Subscriber interface

```python
# evaluation/progress.py

class Subscriber(Protocol):
    def handle(self, event: ProgressEvent) -> None: ...
```

A subscriber is anything with `handle(event)`. Plain callables also satisfy the contract via a `CallableSubscriber` adapter if needed for tests.

### 3.3 ProgressState becomes the bus

`ProgressState` keeps its existing fields (tokens, cost, tool_log, milestones, etc.) and gains:

- `stage_name: StageName | None` and `session_id: str | None` — populated by `stage_start()`. Needed because `StatusText` events are formatted via `format_progress(stage, ProgressState)`, which today receives `stage` as a separate argument from the runner. Once `ProgressState` emits its own `StatusText`, it must know the stage.
- A subscriber registry plus mutation methods that emit events:

```python
class ProgressState:
    # ... existing fields ...
    _subscribers: list[Subscriber] = field(default_factory=list, init=False)

    def subscribe(self, sub: Subscriber) -> None:
        self._subscribers.append(sub)

    def _emit(self, event: ProgressEvent) -> None:
        for s in self._subscribers:
            s.handle(event)

    def add_tool_call(self, name: str, target: str) -> None:
        elapsed = time.monotonic() - self.start_time
        self.tool_log.append(ToolEntry(timestamp=elapsed, name=name, target=target))
        self._emit(ToolCall(name=name, target=target, timestamp=elapsed))

    def update_metrics(self, tin: int, tout: int, cost: float, turns: int) -> None:
        self.input_tokens, self.output_tokens = tin, tout
        self.total_cost_usd, self.num_turns = cost, turns
        elapsed = time.monotonic() - self.start_time
        metrics = Metrics(tin, tout, cost, turns, elapsed)
        self._emit(metrics)
        self._emit(StatusText(format_progress(self.stage_name, self)))

    def open_group(self, title: str) -> None: ...
    def close_group(self) -> None: ...
    def add_milestone(self, label: str) -> None: ...
    def stage_start(self, stage: StageName, session_id: str) -> None: ...
    def stage_end(self, success: bool, error: str | None) -> None: ...
```

The runner stops calling `progress_adapter.on_*` and stops accepting `on_progress`. It only mutates `ProgressState` through these methods.

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

    def handle(self, event):
        if isinstance(event, StatusText) and self._throttle.ready():
            self._comment.update(event.text)
        elif isinstance(event, Milestone):
            self._comment.append(f"✨ {event.label}")    # immediate, rare
        elif isinstance(event, StageEnd):
            icon = "✅" if event.success else "❌"
            self._comment.finalize(
                f"{icon} {event.stage.value} done — "
                f"${event.final_metrics.total_cost_usd:.2f}, "
                f"{event.final_metrics.num_turns} turns"
            )
```

`Throttle` is a 10-line shared utility in `evaluation/progress.py`:

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
ctx.progress.subscribe(GhActionsLogSubscriber())
ctx.progress.subscribe(GhCommentSubscriber(comment))
```

```python
# cli_local.py
ctx.progress.subscribe(ConsoleSubscriber())
```

Tests:

```python
recorder = RecordingSubscriber()
ctx.progress.subscribe(recorder)
# ... run stage ...
assert isinstance(recorder.events[0], StageStart)
assert any(isinstance(e, ToolCall) and e.name == "Skill" for e in recorder.events)
```

### 3.6 Terminal-state guarantee

`StageEnd` is emitted from `ProgressState.stage_end()` immediately after the runner receives the SDK's `ResultMessage`. It carries the authoritative final metrics from the result message (not a snapshot mid-stream), and it is **never throttled** — every subscriber receives it. This fixes a latent bug today where the 5 s throttle could swallow the very last `Metrics` update before the run ended, leaving the GitHub comment showing stale numbers until `finalize_comment` (called separately from `dispatch.py`) cleaned up.

### 3.7 Ordering and error containment

- Subscribers receive events in the order `subscribe()` was called.
- A subscriber raising an exception logs the failure (via `logging.getLogger("a2sdlc.progress")`) and is **skipped for the remainder of the stage**. One broken subscriber must not crash the run.
- Subscribers are called synchronously on the runner's event loop. No queues, no threads. The event volume is low (≤ ~100 per stage) and subscribers are expected to be cheap (printing, deque appends, throttled API calls).

---

## 4. Layout

```
src/a2sdlc/
  evaluation/
    progress.py                  # ProgressState + ProgressEvent taxonomy
                                 # + Subscriber Protocol + Throttle utility
  adapters/
    console_subscriber.py        # was progress_console.py
    gh_actions_subscriber.py     # was progress_gh_actions.py
    gh_comment_subscriber.py     # NEW
    factory.py                   # build_*_subscriber functions
  pipeline/
    runner.py                    # mutates ProgressState only; no on_progress kwarg
    dispatch.py                  # registers subscribers per deployment context
  cli_local.py                   # registers ConsoleSubscriber
tests/
  evaluation/test_progress_events.py   # event emission, ordering, throttle
  adapters/test_*_subscriber.py        # one suite per subscriber
```

Hexagonal-lite invariant from `CLAUDE.md` holds: subscribers are I/O concerns → `adapters/`. Event taxonomy and `Subscriber` Protocol are progress-domain → `evaluation/`. `domain/` stays untouched.

---

## 5. Migration

Strict replacement, no compat shim:

1. Add `ProgressEvent`, `Subscriber`, `Throttle`, mutation-and-emit methods to `evaluation/progress.py`.
2. Add `RecordingSubscriber` in `tests/fakes.py`.
3. Rewrite `ConsoleProgressAdapter` → `ConsoleSubscriber`. Rename file. Same surface (rich.Live), now driven by events.
4. Rewrite `GhActionsProgressAdapter` → `GhActionsLogSubscriber`. Rename file. Same `::group::` markers.
5. Add `GhCommentSubscriber` (new file). Move the lambda logic from `dispatch.py:252` into it.
6. Update `pipeline/runner.py`: drop `on_progress` kwarg, drop direct `progress_adapter.on_*` calls, mutate `ProgressState` instead.
7. Delete `ProgressAdapter` Protocol from `adapters/protocols.py`.
8. Update `dispatch.py` and `cli_local.py` to register subscribers instead of constructing a single adapter.
9. Delete `update_metrics()` from the old console adapter (no longer applicable; the new console subscriber handles `Metrics` events directly).
10. Rewrite tests that mocked `ProgressAdapter`. Use `RecordingSubscriber`.

No feature flag, no parallel rollout — there is one consumer of this code (the engine itself), and the contract is internal.

---

## 6. Testing

- **Unit:** `ProgressState` emits the right events at the right time. Order across `subscribe()` calls. Subscriber-raises-exception is contained. `Throttle` admits the first call and rejects within-window subsequent calls.
- **Per subscriber:** `RecordingSubscriber` captures everything; concrete subscribers (`ConsoleSubscriber`, `GhActionsLogSubscriber`, `GhCommentSubscriber`) tested in isolation against synthetic event sequences.
- **Integration:** existing fake-runner SPEC→IMPLEMENT test gains a `RecordingSubscriber` to assert the event sequence (`StageStart → ToolCall* → Metrics* → StageEnd`).
- **Smoke:** the existing `a2sdlc-smoke` workspace re-runs SPEC + IMPLEMENT; status bar must show real numbers; GitHub-flow path is **not** smoke-tested locally (no GH token in smoke), but `GhCommentSubscriber` gets a unit test using a fake comment handle.

---

## 7. Risks & Trade-offs

| Risk | Mitigation |
|---|---|
| ProgressState gains behavior (stops being a pure dataclass) | Keep behavior narrow: only `subscribe`, mutation methods, `_emit`. No business logic. |
| Subscriber list mutated mid-stage (race) | Document: `subscribe()` only at composition time, before `stage_start()` fires. Not a public-API concern. |
| Event taxonomy churn (adding/renaming events later) | Tagged union with explicit names; subscribers ignore unknown types via `isinstance` filter — additive changes are safe. |
| One slow subscriber stalls the runner | Subscribers are synchronous and expected to be cheap. If a future subscriber needs async (Slack webhook), it spawns its own task and returns immediately from `handle`. |
| Refactor scope larger than the symptom (status bar bug) | Acknowledged. Justified by the smell already producing two real defects, plus the imminent third-subscriber needs from `eval-system` and `agentic-web-stack`. |

---

## 8. Out of Scope

- Async subscribers / queues / backpressure.
- Persisting the event stream to disk for replay.
- Cross-stage event correlation (use MLflow parent runs).
- Restoring the agent-level filesystem fence (separate punch-list item).
- Threading `review_cycles` into `get_session_id` (separate punch-list item).

---

## 9. Acceptance

- `pyright`, `ruff`, `pytest` all green.
- All existing 496 tests pass (after mock-replacement updates).
- Local smoke run shows non-zero tokens / cost / turns updating live in the console status bar.
- `ProgressAdapter` Protocol no longer exists in the codebase.
- `on_progress` kwarg no longer exists on `runner.py` / `stage_executor.py` / `StageRunner` Protocol.
- `git grep "on_progress" src/` returns no matches.
- `git grep "ProgressAdapter" src/` returns no matches.
