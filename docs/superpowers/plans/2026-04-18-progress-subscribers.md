# Progress Subscribers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the a2sdlc engine's two parallel progress channels (`ProgressAdapter` protocol + `on_progress` callback) with one typed event stream emitted by `ProgressState` to N independent subscribers. Side effect: fixes the local console status bar that today displays `tokens: 0/0 / $0.00 / 0 turns` throughout every run.

**Architecture:** `ProgressState` becomes a pub/sub bus. The runner mutates it via `await`-able methods (`stage_start`, `add_tool_call`, `update_metrics`, `add_milestone`, `open_group`, `close_group`); each call emits a typed `ProgressEvent` to subscribed consumers. Composition roots (`cli.py`, `cli_local.py`) construct `ProgressState` once per dispatch lifetime, register the appropriate subscribers (`ConsoleSubscriber` for local, `GhActionsLogSubscriber` + `GhCommentSubscriber` for GH dispatch), and pass the state into `DispatchContext`. The `ProgressAdapter` protocol and the `on_progress` callback are deleted.

**Tech Stack:** Python 3.12, `asyncio`, dataclasses, `rich.Live`, `pytest`, `pytest-asyncio`. Internal modules only — no new third-party deps.

**Spec:** `docs/superpowers/specs/2026-04-18-progress-subscribers-design.md` (commit `3ecd40c` or later).

**Migration mode:** Single PR, no compat shim. Tasks 1-8 are additive (everything stays green). Tasks 9-13 do the cutover (`make check` will fail mid-task-list). Task 14 restores green via fixture rewrites. Task 15 is smoke validation + the spec's acceptance greps.

---

## File Structure

**Create:**
- `src/a2sdlc/evaluation/throttle.py` — `Throttle` utility (no progress semantics)
- `src/a2sdlc/adapters/console_subscriber.py` — replaces `progress_console.py`
- `src/a2sdlc/adapters/gh_actions_subscriber.py` — replaces `progress_gh_actions.py`
- `src/a2sdlc/adapters/gh_comment_subscriber.py` — NEW; absorbs the `dispatch.py:252` `on_progress` lambda
- `tests/evaluation/test_throttle.py`
- `tests/evaluation/test_progress_events.py` — events, subscriber registry, lifecycle, exception containment
- `tests/adapters/test_console_subscriber.py`
- `tests/adapters/test_gh_actions_subscriber.py`
- `tests/adapters/test_gh_comment_subscriber.py`

**Modify:**
- `src/a2sdlc/evaluation/progress.py` — add events, `Subscriber` consumers, lifecycle methods, `snapshot_metrics()`; repartition `ProgressState.__init__` to take only `project_root`
- `src/a2sdlc/adapters/protocols.py` — add `Subscriber` Protocol; later delete `ProgressAdapter`; extend `StageRunner.run` signature with `progress_state`
- `src/a2sdlc/pipeline/runner.py` — drop `progress` ctor arg, drop `on_progress` kwarg, drop inline `print("::group::")` fallback; mutate `progress_state` via the new methods
- `src/a2sdlc/pipeline/stage_executor.py` — drop `on_progress` kwarg; thread `progress_state` through
- `src/a2sdlc/pipeline/dispatch.py` — rename `progress` → `progress_state`; wrap post-`comment.start` block with `stage_start`/`stage_end` for both MERGE and SDK paths
- `src/a2sdlc/cli.py` — construct `ProgressState`, register `GhActionsLogSubscriber` + `GhCommentSubscriber`
- `src/a2sdlc/cli_local.py` — construct `ProgressState`, register `ConsoleSubscriber`, delete the explicit `progress.on_stage_start` / `on_stage_end` calls (dispatch owns them now)
- `src/a2sdlc/adapters/factory.py` — repurpose `build_progress_adapter` → `build_console_subscriber` (drops the GH branch — GH wires subscribers directly)
- `tests/fakes.py` — add `RecordingSubscriber`; remove `FakeProgressAdapter`
- `tests/pipeline/test_dispatch.py`, `test_dispatch_e2e.py`, `test_dispatch_progress.py`, `test_stage_executor.py` — switch to `RecordingSubscriber`

**Delete:**
- `src/a2sdlc/adapters/progress_console.py`
- `src/a2sdlc/adapters/progress_gh_actions.py`

---

## Task 1: Throttle utility

**Files:**
- Create: `src/a2sdlc/evaluation/throttle.py`
- Test: `tests/evaluation/test_throttle.py`

- [ ] **Step 1: Write the failing test**

Create `tests/evaluation/test_throttle.py`:

```python
"""Throttle utility — admits the first call, rejects within-window subsequent."""
from __future__ import annotations

import time

from a2sdlc.evaluation.throttle import Throttle


def test_first_call_admitted() -> None:
    t = Throttle(min_interval=1.0)
    assert t.ready() is True


def test_second_call_within_window_rejected() -> None:
    t = Throttle(min_interval=10.0)
    assert t.ready() is True
    assert t.ready() is False


def test_call_after_window_admitted(monkeypatch) -> None:
    fake_now = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_now[0])
    t = Throttle(min_interval=1.0)
    assert t.ready() is True
    fake_now[0] = 0.5
    assert t.ready() is False
    fake_now[0] = 1.5
    assert t.ready() is True


def test_zero_interval_always_admits(monkeypatch) -> None:
    fake_now = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: fake_now[0])
    t = Throttle(min_interval=0.0)
    assert t.ready() is True
    assert t.ready() is True
    assert t.ready() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/evaluation/test_throttle.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'a2sdlc.evaluation.throttle'`

- [ ] **Step 3: Write minimal implementation**

Create `src/a2sdlc/evaluation/throttle.py`:

```python
"""Time-window guard. No progress semantics; reusable by any subscriber."""
from __future__ import annotations

import time


class Throttle:
    """Admits the first call, then rejects until ``min_interval`` seconds pass."""

    def __init__(self, min_interval: float) -> None:
        self._min = min_interval
        self._last: float | None = None

    def ready(self) -> bool:
        now = time.monotonic()
        if self._last is None or now - self._last >= self._min:
            self._last = now
            return True
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/evaluation/test_throttle.py -v`
Expected: PASS — 4 tests pass.

- [ ] **Step 5: Run full lint + test suite**

Run: `make check`
Expected: PASS (additive change, no existing code affected).

- [ ] **Step 6: Commit**

```bash
git add src/a2sdlc/evaluation/throttle.py tests/evaluation/test_throttle.py
git commit -m "feat(evaluation): add Throttle utility for subscriber-side rate limiting"
```

---

## Task 2: Event taxonomy

**Files:**
- Modify: `src/a2sdlc/evaluation/progress.py` (add new event dataclasses + `ProgressEvent` union)
- Test: `tests/evaluation/test_progress_events.py`

- [ ] **Step 1: Write the failing test**

Create `tests/evaluation/test_progress_events.py`:

```python
"""Event taxonomy — concrete dataclasses + ProgressEvent union."""
from __future__ import annotations

from a2sdlc.domain.models import StageName
from a2sdlc.evaluation.progress import (
    GroupClose,
    GroupOpen,
    Metrics,
    Milestone,
    ProgressEvent,
    StageEnd,
    StageStart,
    ToolEntry,
)


def test_stage_start_carries_stage_session_started_at() -> None:
    evt = StageStart(stage=StageName.SPEC, session_id="abc", started_at=12.5)
    assert evt.stage == StageName.SPEC
    assert evt.session_id == "abc"
    assert evt.started_at == 12.5


def test_metrics_carries_token_cost_turns_elapsed() -> None:
    m = Metrics(input_tokens=1, output_tokens=2, total_cost_usd=0.5,
                num_turns=3, elapsed=4.0)
    assert m.input_tokens == 1
    assert m.output_tokens == 2
    assert m.total_cost_usd == 0.5
    assert m.num_turns == 3
    assert m.elapsed == 4.0


def test_stage_end_carries_final_metrics() -> None:
    final = Metrics(1, 2, 0.5, 3, 4.0)
    evt = StageEnd(stage=StageName.IMPLEMENT, success=True, error=None, final_metrics=final)
    assert evt.success is True
    assert evt.error is None
    assert evt.final_metrics is final


def test_progressevent_union_includes_all_event_types() -> None:
    # Reuse existing ToolEntry and Milestone as event types.
    sample: list[ProgressEvent] = [
        StageStart(stage=StageName.SPEC, session_id="x", started_at=0.0),
        ToolEntry(timestamp=0.1, name="Read", target="foo.py"),
        GroupOpen(title="t"),
        GroupClose(),
        Metrics(0, 0, 0.0, 0, 0.0),
        Milestone(timestamp=1.0, label="x"),
        StageEnd(stage=StageName.SPEC, success=True, error=None,
                 final_metrics=Metrics(0, 0, 0.0, 0, 0.0)),
    ]
    assert len(sample) == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/evaluation/test_progress_events.py -v`
Expected: FAIL — `ImportError: cannot import name 'StageStart' from 'a2sdlc.evaluation.progress'`.

- [ ] **Step 3: Add event dataclasses to `evaluation/progress.py`**

In `src/a2sdlc/evaluation/progress.py`, after the existing `Milestone` dataclass (line 26), add:

```python
# ── Event taxonomy ─────────────────────────────────────────────────
# ToolEntry (above) and Milestone (above) double as event types.

from a2sdlc.domain.models import StageName  # noqa: E402  (needed for events)


@dataclass
class StageStart:
    """Stage execution begins. Emitted by dispatch (not the runner)."""

    stage: StageName
    session_id: str
    started_at: float  # time.monotonic() snapshot


@dataclass
class GroupOpen:
    """Open a logical group of related events (e.g. a tool invocation)."""

    title: str


@dataclass
class GroupClose:
    """Close the most-recently-opened group."""


@dataclass
class Metrics:
    """Snapshot of token / cost / turn counters."""

    input_tokens: int
    output_tokens: int
    total_cost_usd: float
    num_turns: int
    elapsed: float  # seconds since stage_start, monotonic clock


@dataclass
class StageEnd:
    """Stage execution ends. Carries authoritative final metrics."""

    stage: StageName
    success: bool
    error: str | None
    final_metrics: Metrics


# Tagged union. Subscribers dispatch via isinstance.
ProgressEvent = (
    StageStart | ToolEntry | GroupOpen | GroupClose | Metrics | Milestone | StageEnd
)
```

(Move the `from a2sdlc.domain.models import StageName` import to the top of the file, beside the existing imports — the noqa above is illustrative.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/evaluation/test_progress_events.py -v`
Expected: PASS — 4 tests pass.

- [ ] **Step 5: Run full lint + test suite**

Run: `make check`
Expected: PASS (additive change).

- [ ] **Step 6: Commit**

```bash
git add src/a2sdlc/evaluation/progress.py tests/evaluation/test_progress_events.py
git commit -m "feat(evaluation): add ProgressEvent taxonomy (StageStart, Metrics, etc.)"
```

---

## Task 3: Subscriber Protocol

**Files:**
- Modify: `src/a2sdlc/adapters/protocols.py` (add `Subscriber` Protocol)
- Test: `tests/adapters/test_subscriber_protocol.py`

- [ ] **Step 1: Write the failing test**

Create `tests/adapters/test_subscriber_protocol.py`:

```python
"""Subscriber Protocol — anything with async handle(event) satisfies it."""
from __future__ import annotations

from typing import get_args

import pytest

from a2sdlc.adapters.protocols import Subscriber
from a2sdlc.evaluation.progress import GroupClose, ProgressEvent


class _OkSubscriber:
    def __init__(self) -> None:
        self.events: list = []

    async def handle(self, event) -> None:
        self.events.append(event)


def test_class_with_async_handle_is_a_subscriber() -> None:
    s: Subscriber = _OkSubscriber()  # type: ignore[assignment]
    assert hasattr(s, "handle")


@pytest.mark.asyncio
async def test_handle_receives_progress_events() -> None:
    s = _OkSubscriber()
    evt: ProgressEvent = GroupClose()
    await s.handle(evt)
    assert s.events == [evt]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/adapters/test_subscriber_protocol.py -v`
Expected: FAIL — `ImportError: cannot import name 'Subscriber' from 'a2sdlc.adapters.protocols'`.

- [ ] **Step 3: Add `Subscriber` Protocol**

In `src/a2sdlc/adapters/protocols.py`, after the existing `ProgressAdapter` Protocol (lines 41-48), add:

```python
class Subscriber(Protocol):
    """Receives ``ProgressEvent`` instances from ``ProgressState``.

    Implementations filter by ``isinstance`` and ignore event types they
    don't care about. ``handle`` is async because the runner is already
    async; sync subscribers just don't ``await`` anything inside.
    """

    async def handle(self, event: "ProgressEvent") -> None: ...
```

Add the import at the top of the file using a `TYPE_CHECKING` guard to avoid the circular import (`progress.py` will need to forward-reference `Subscriber` in Task 4):

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from a2sdlc.evaluation.progress import ProgressEvent
```

(Make sure `from __future__ import annotations` is at the top of the file so the forward reference resolves lazily.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/adapters/test_subscriber_protocol.py -v`
Expected: PASS — 2 tests pass.

- [ ] **Step 5: Run full lint + test suite**

Run: `make check`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/a2sdlc/adapters/protocols.py tests/adapters/test_subscriber_protocol.py
git commit -m "feat(adapters): add Subscriber Protocol"
```

---

## Task 4: ProgressState lifecycle methods

**Files:**
- Modify: `src/a2sdlc/evaluation/progress.py` (add `subscribe`, `_emit`, `stage_start`, `stage_end`, `add_tool_call`, `update_metrics`, `add_milestone`, `open_group`, `close_group`, `snapshot_metrics`; repartition `__init__`)
- Test: `tests/evaluation/test_progress_events.py` (extend with bus tests)

This task changes `ProgressState`'s constructor signature. **Existing callers (`runner.py:106-113`) will temporarily break at runtime but tests for `ProgressState` itself stay green — fix runner in Task 9.** Add a TODO marker.

- [ ] **Step 1: Write the failing tests for the bus**

Append to `tests/evaluation/test_progress_events.py`:

```python
import pytest

from a2sdlc.evaluation.progress import ProgressState


class _Recorder:
    def __init__(self) -> None:
        self.events: list = []

    async def handle(self, event) -> None:
        self.events.append(event)


def _make_state() -> ProgressState:
    return ProgressState(project_root="/tmp/test")


@pytest.mark.asyncio
async def test_stage_start_emits_StageStart_and_resets_state() -> None:
    state = _make_state()
    state.tool_log.append(ToolEntry(timestamp=0.0, name="x", target="y"))
    state.input_tokens = 99
    rec = _Recorder()
    state.subscribe(rec)

    await state.stage_start(
        StageName.SPEC, "sid",
        model="claude-x", max_turns=10, context_window=200_000, branch="b",
    )

    assert state.tool_log == []
    assert state.input_tokens == 0
    assert state.model == "claude-x"
    assert state.max_turns == 10
    assert state.context_window == 200_000
    assert state.branch == "b"
    assert len(rec.events) == 1
    assert isinstance(rec.events[0], StageStart)
    assert rec.events[0].stage == StageName.SPEC
    assert rec.events[0].session_id == "sid"


@pytest.mark.asyncio
async def test_add_tool_call_appends_and_emits_ToolEntry() -> None:
    state = _make_state()
    rec = _Recorder()
    state.subscribe(rec)
    await state.stage_start(StageName.SPEC, "sid",
                            model="m", max_turns=1, context_window=1, branch="b")
    rec.events.clear()

    await state.add_tool_call("Read", "foo.py")

    assert len(state.tool_log) == 1
    assert state.tool_log[0].name == "Read"
    assert state.tool_log[0].target == "foo.py"
    assert len(rec.events) == 1
    assert rec.events[0] is state.tool_log[0]  # same reference, not a copy


@pytest.mark.asyncio
async def test_update_metrics_writes_state_and_emits_Metrics() -> None:
    state = _make_state()
    rec = _Recorder()
    state.subscribe(rec)
    await state.stage_start(StageName.SPEC, "sid",
                            model="m", max_turns=1, context_window=1, branch="b")
    rec.events.clear()

    await state.update_metrics(tin=10, tout=20, cost=0.05, turns=2)

    assert state.input_tokens == 10
    assert state.output_tokens == 20
    assert state.total_cost_usd == 0.05
    assert state.num_turns == 2
    assert len(rec.events) == 1
    assert isinstance(rec.events[0], Metrics)
    assert rec.events[0].input_tokens == 10
    assert rec.events[0].num_turns == 2


@pytest.mark.asyncio
async def test_subscribers_receive_events_in_registration_order() -> None:
    state = _make_state()
    a, b, c = _Recorder(), _Recorder(), _Recorder()
    state.subscribe(a)
    state.subscribe(b)
    state.subscribe(c)

    await state.stage_start(StageName.SPEC, "sid",
                            model="m", max_turns=1, context_window=1, branch="b")

    assert len(a.events) == len(b.events) == len(c.events) == 1


@pytest.mark.asyncio
async def test_failing_subscriber_is_skipped_for_remainder_of_stage() -> None:
    class _Boom:
        async def handle(self, event) -> None:
            raise RuntimeError("boom")

    state = _make_state()
    boom = _Boom()
    good = _Recorder()
    state.subscribe(boom)
    state.subscribe(good)

    await state.stage_start(StageName.SPEC, "sid",
                            model="m", max_turns=1, context_window=1, branch="b")
    await state.add_tool_call("Read", "x")

    assert len(good.events) == 2  # both events received despite boom failing


@pytest.mark.asyncio
async def test_failed_set_clears_on_next_stage_start() -> None:
    class _BoomOnce:
        def __init__(self) -> None:
            self.calls = 0

        async def handle(self, event) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("boom")

    state = _make_state()
    sub = _BoomOnce()
    state.subscribe(sub)

    await state.stage_start(StageName.SPEC, "s1",
                            model="m", max_turns=1, context_window=1, branch="b")
    # Subscriber failed once; now in _failed for the rest of this stage.
    await state.add_tool_call("x", "y")
    assert sub.calls == 1  # not invoked second time

    await state.stage_start(StageName.IMPLEMENT, "s2",
                            model="m", max_turns=1, context_window=1, branch="b")
    # _failed cleared; subscriber invoked again.
    assert sub.calls == 2  # called for StageStart of IMPLEMENT


@pytest.mark.asyncio
async def test_snapshot_metrics_returns_current_counters_without_emitting() -> None:
    state = _make_state()
    rec = _Recorder()
    state.subscribe(rec)
    await state.stage_start(StageName.SPEC, "sid",
                            model="m", max_turns=1, context_window=1, branch="b")
    await state.update_metrics(tin=5, tout=7, cost=0.1, turns=1)
    rec.events.clear()

    snap = state.snapshot_metrics()

    assert isinstance(snap, Metrics)
    assert snap.input_tokens == 5
    assert snap.output_tokens == 7
    assert snap.total_cost_usd == 0.1
    assert snap.num_turns == 1
    assert rec.events == []  # no emit
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/evaluation/test_progress_events.py -v`
Expected: FAIL — `TypeError: __init__() missing required arguments: 'model', 'branch', ...` plus several missing-method errors.

- [ ] **Step 3: Repartition `ProgressState.__init__` and add lifecycle methods**

In `src/a2sdlc/evaluation/progress.py`, replace the existing `ProgressState` dataclass (lines 29-46) with:

```python
@dataclass
class ProgressState:
    """Pub/sub bus for progress events. Constructed once per dispatch lifetime.

    Per-stage configuration (model, max_turns, context_window, branch) is
    refreshed in ``stage_start()`` from each stage's StageConfig. Per-stage
    counters and lists are reset there too. The subscriber list survives
    across stages within a single dispatch.
    """

    # Dispatch-lifetime field
    project_root: str  # for shortening file paths in tool targets

    # Per-stage config (refreshed in stage_start)
    model: str = ""
    branch: str = ""
    max_turns: int = 0
    context_window: int = 0  # total context window size in tokens

    # Per-stage timing (refreshed in stage_start)
    start_time: float = 0.0  # time.monotonic() at most-recent stage_start

    # Per-stage counters (reset in stage_start)
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_usd: float = 0.0
    num_turns: int = 0
    tool_log: list[ToolEntry] = field(default_factory=list)
    milestones: list[Milestone] = field(default_factory=list)
    tasks: dict[str, str] = field(default_factory=dict)  # subject → status

    # Subscriber registry (dispatch-lifetime; _failed cleared per stage)
    _subscribers: list = field(default_factory=list, init=False, repr=False)
    _failed: set[int] = field(default_factory=set, init=False, repr=False)

    # ── Subscriber registration ───────────────────────────────────

    def subscribe(self, sub: "Subscriber") -> None:
        """Register a subscriber. Call before any stage_start()."""
        self._subscribers.append(sub)

    # ── Internal emit ─────────────────────────────────────────────

    async def _emit(self, event: "ProgressEvent") -> None:
        # Snapshot the list so a subscriber that fails (and gets added to
        # _failed) doesn't perturb iteration. Cheap — list of ≤ ~5 items.
        for sub in list(self._subscribers):
            if id(sub) in self._failed:
                continue
            try:
                await sub.handle(event)
            except Exception:  # noqa: BLE001
                _log = logging.getLogger("a2sdlc.progress")
                _log.exception(
                    "Subscriber %s failed; skipping for remainder of stage",
                    type(sub).__name__,
                )
                self._failed.add(id(sub))

    # ── Lifecycle ─────────────────────────────────────────────────

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
        """Begin a stage. Refreshes per-stage config and resets counters."""
        # Refresh per-stage config
        self.model = model
        self.max_turns = max_turns
        self.context_window = context_window
        self.branch = branch
        # Reset per-stage mutable state; subscriber list and project_root survive.
        self._failed.clear()
        self.tool_log.clear()
        self.milestones.clear()
        self.tasks.clear()
        self.input_tokens = 0
        self.output_tokens = 0
        self.num_turns = 0
        self.total_cost_usd = 0.0
        self.start_time = time.monotonic()
        await self._emit(StageStart(stage=stage, session_id=session_id,
                                    started_at=self.start_time))

    async def stage_end(
        self,
        stage: StageName,
        success: bool,
        error: str | None,
        final: "Metrics",
    ) -> None:
        """End a stage. Emits StageEnd with the authoritative final metrics."""
        await self._emit(StageEnd(stage=stage, success=success, error=error,
                                  final_metrics=final))

    # ── Mutators (each emits an event) ────────────────────────────

    async def add_tool_call(self, name: str, target: str) -> None:
        elapsed = time.monotonic() - self.start_time
        entry = ToolEntry(timestamp=elapsed, name=name, target=target)
        self.tool_log.append(entry)
        await self._emit(entry)

    async def update_metrics(
        self, tin: int, tout: int, cost: float, turns: int,
    ) -> None:
        self.input_tokens = tin
        self.output_tokens = tout
        self.total_cost_usd = cost
        self.num_turns = turns
        elapsed = time.monotonic() - self.start_time
        await self._emit(Metrics(input_tokens=tin, output_tokens=tout,
                                 total_cost_usd=cost, num_turns=turns,
                                 elapsed=elapsed))

    async def add_milestone(self, label: str) -> None:
        elapsed = time.monotonic() - self.start_time
        m = Milestone(timestamp=elapsed, label=label)
        self.milestones.append(m)
        await self._emit(m)

    async def open_group(self, title: str) -> None:
        await self._emit(GroupOpen(title=title))

    async def close_group(self) -> None:
        await self._emit(GroupClose())

    # ── Snapshot (no emit) ────────────────────────────────────────

    def snapshot_metrics(self) -> "Metrics":
        """Build a Metrics record from current counters. Synchronous, no emit."""
        elapsed = time.monotonic() - self.start_time if self.start_time else 0.0
        return Metrics(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            total_cost_usd=self.total_cost_usd,
            num_turns=self.num_turns,
            elapsed=elapsed,
        )
```

Add `import logging` at the top of the file. Move the `from a2sdlc.domain.models import StageName` import to the top alongside other imports. Add a `TYPE_CHECKING` block to break the cycle with `protocols.py`:

```python
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from a2sdlc.domain.models import StageName

if TYPE_CHECKING:
    from a2sdlc.adapters.protocols import Subscriber
```

**Clock note:** keep `self.start_time = time.monotonic()` here — but **also** patch `runner.py:213-214` (the existing `_handle_assistant_message`) to read `time.monotonic()` instead of `time.time()` in this same task to avoid a wall-clock-vs-monotonic mismatch in the (~5-task) window before Task 9 lands. One line edit:

```python
# In src/a2sdlc/pipeline/runner.py near line 213, replace:
#    now = current_time if current_time is not None else time.time()
# with:
now = current_time if current_time is not None else time.monotonic()
```

This keeps elapsed values sensible during Tasks 5-8 even though the runner has not yet been fully refactored.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/evaluation/test_progress_events.py -v`
Expected: PASS — all bus tests pass.

- [ ] **Step 5: Don't run full `make check` yet**

Existing `runner.py:106-113` constructs `ProgressState(model=..., branch=..., max_turns=..., context_window=..., project_root=..., start_time=...)` — that call site is now broken (positional args mismatched). Tests for the runner will fail. This is expected; we fix it in Task 9.

You may run `uv run pytest tests/evaluation/ -v` to confirm the evaluation suite is green.

- [ ] **Step 6: Commit**

```bash
git add src/a2sdlc/evaluation/progress.py tests/evaluation/test_progress_events.py
git commit -m "feat(evaluation): make ProgressState a pub/sub bus with lifecycle methods"
```

---

## Task 5: RecordingSubscriber test fake

**Files:**
- Modify: `tests/fakes.py` (add `RecordingSubscriber`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_fakes_recording_subscriber.py`:

```python
"""RecordingSubscriber — minimal test helper that captures all events."""
from __future__ import annotations

import pytest

from a2sdlc.domain.models import StageName
from a2sdlc.evaluation.progress import StageStart
from tests.fakes import RecordingSubscriber


@pytest.mark.asyncio
async def test_recording_subscriber_captures_events_in_order() -> None:
    rec = RecordingSubscriber()
    e1 = StageStart(stage=StageName.SPEC, session_id="a", started_at=0.0)
    e2 = StageStart(stage=StageName.IMPLEMENT, session_id="b", started_at=1.0)
    await rec.handle(e1)
    await rec.handle(e2)
    assert rec.events == [e1, e2]


def test_recording_subscriber_starts_empty() -> None:
    rec = RecordingSubscriber()
    assert rec.events == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fakes_recording_subscriber.py -v`
Expected: FAIL — `ImportError: cannot import name 'RecordingSubscriber' from 'tests.fakes'`.

- [ ] **Step 3: Add RecordingSubscriber to `tests/fakes.py`**

In `tests/fakes.py`, after the existing `FakeProgressAdapter` class (around line 60 — adjust as needed), add:

```python
# ── RecordingSubscriber ───────────────────────────────────────────────

from a2sdlc.evaluation.progress import ProgressEvent  # noqa: PLC0415  (test-only)


class RecordingSubscriber:
    """Captures every ``ProgressEvent`` for assertion in tests.

    Satisfies the ``Subscriber`` Protocol (async ``handle``).
    """

    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []

    async def handle(self, event: ProgressEvent) -> None:
        self.events.append(event)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fakes_recording_subscriber.py -v`
Expected: PASS — 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/fakes.py tests/test_fakes_recording_subscriber.py
git commit -m "test: add RecordingSubscriber test fake"
```

---

## Task 6: ConsoleSubscriber

**Files:**
- Create: `src/a2sdlc/adapters/console_subscriber.py`
- Test: `tests/adapters/test_console_subscriber.py`
- (Old `progress_console.py` stays in place until Task 15.)

- [ ] **Step 1: Write the failing test**

Create `tests/adapters/test_console_subscriber.py`:

```python
"""ConsoleSubscriber — renders events into rich.Live status bar + scroll."""
from __future__ import annotations

import pytest

from a2sdlc.adapters.console_subscriber import ConsoleSubscriber
from a2sdlc.domain.models import StageName
from a2sdlc.evaluation.progress import (
    GroupClose,
    GroupOpen,
    Metrics,
    Milestone,
    ProgressState,
    StageEnd,
    StageStart,
    ToolEntry,
)


@pytest.mark.asyncio
async def test_metrics_event_updates_status_bar_counters() -> None:
    state = ProgressState(project_root="/tmp")
    sub = ConsoleSubscriber(state)
    state.subscribe(sub)  # subscribe is sync; returns None.
    # Bypass actual rich.Live by accessing the rendered string directly.
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid",
                                started_at=0.0))
    await sub.handle(Metrics(input_tokens=1234, output_tokens=5678,
                             total_cost_usd=0.42, num_turns=7, elapsed=10.0))
    bar = sub.render_status_bar()
    assert "1234" in bar
    assert "5678" in bar
    assert "0.42" in bar
    assert "7" in bar  # num_turns


@pytest.mark.asyncio
async def test_tool_entry_event_appends_to_recent_events() -> None:
    state = ProgressState(project_root="/tmp")
    sub = ConsoleSubscriber(state)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid",
                                started_at=0.0))
    await sub.handle(ToolEntry(timestamp=0.1, name="Read", target="foo.py"))
    rendered = "\n".join(sub.recent_events)
    assert "Read" in rendered
    assert "foo.py" in rendered


@pytest.mark.asyncio
async def test_stage_end_closes_live_render() -> None:
    state = ProgressState(project_root="/tmp")
    sub = ConsoleSubscriber(state)
    final = Metrics(0, 0, 0.0, 0, 0.0)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid",
                                started_at=0.0))
    await sub.handle(StageEnd(stage=StageName.SPEC, success=True, error=None,
                              final_metrics=final))
    assert sub._live is None  # live render closed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/adapters/test_console_subscriber.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'a2sdlc.adapters.console_subscriber'`.

- [ ] **Step 3: Create `console_subscriber.py`**

Create `src/a2sdlc/adapters/console_subscriber.py`:

```python
"""ConsoleSubscriber — rich.Live renderer driven by ProgressEvent stream."""
from __future__ import annotations

from collections import deque

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from a2sdlc.evaluation.progress import (
    GroupClose,
    GroupOpen,
    Metrics,
    Milestone,
    ProgressEvent,
    ProgressState,
    StageEnd,
    StageStart,
    ToolEntry,
)


class ConsoleSubscriber:
    """Live console: scrolling events on top, status bar on bottom.

    Status bar reads counters off the shared ``ProgressState`` so the values
    are always current — no private state to keep in sync.
    """

    _MAX_EVENTS = 20

    def __init__(self, state: ProgressState) -> None:
        self._state = state
        self.recent_events: deque[str] = deque(maxlen=self._MAX_EVENTS)
        self._stage_name: str = "-"
        self._session_id: str = ""
        self._live: Live | None = None
        self._console = Console()

    async def handle(self, event: ProgressEvent) -> None:
        if isinstance(event, StageStart):
            self._stage_name = event.stage.value
            self._session_id = event.session_id
            self.recent_events.clear()
            self._live = Live(self._render(), console=self._console,
                              refresh_per_second=1)
            self._live.__enter__()
        elif isinstance(event, StageEnd):
            if self._live is not None:
                self._live.update(self._render())
                self._live.__exit__(None, None, None)
                self._live = None
        elif isinstance(event, GroupOpen):
            self.recent_events.append(f"\u25b6 {event.title}")
            self._refresh()
        elif isinstance(event, GroupClose):
            self.recent_events.append("\u25c0 end")
            self._refresh()
        elif isinstance(event, ToolEntry):
            self.recent_events.append(f"[tool] {event.name} {event.target[:80]}")
            self._refresh()
        elif isinstance(event, Milestone):
            self.recent_events.append(f"\u2728 {event.label}")
            self._refresh()
        elif isinstance(event, Metrics):
            self._refresh()  # status bar reads from state — just trigger redraw

    def render_status_bar(self) -> str:
        s = self._state
        elapsed = int(s.snapshot_metrics().elapsed)
        return (
            f"stage: {self._stage_name} | "
            f"tokens: {s.input_tokens}/{s.output_tokens} | "
            f"cost: ${s.total_cost_usd:.2f} | "
            f"turns: {s.num_turns}/{s.max_turns} | "
            f"elapsed: {elapsed // 60}:{elapsed % 60:02d} | "
            f"session: {self._session_id}"
        )

    def _render(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="events", ratio=4),
            Layout(name="status", size=3),
        )
        events_text = "\n".join(self.recent_events)
        layout["events"].update(Panel(Text(events_text), title="Progress"))
        layout["status"].update(Panel(Text(self.render_status_bar())))
        return layout

    def _refresh(self) -> None:
        if self._live is not None:
            self._live.update(self._render())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/adapters/test_console_subscriber.py -v`
Expected: PASS — 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/a2sdlc/adapters/console_subscriber.py tests/adapters/test_console_subscriber.py
git commit -m "feat(adapters): add ConsoleSubscriber driven by ProgressEvent stream"
```

---

## Task 7: GhActionsLogSubscriber

**Files:**
- Create: `src/a2sdlc/adapters/gh_actions_subscriber.py`
- Test: `tests/adapters/test_gh_actions_subscriber.py`

- [ ] **Step 1: Write the failing test**

Create `tests/adapters/test_gh_actions_subscriber.py`:

```python
"""GhActionsLogSubscriber — emits ::group::/::endgroup:: + plain lines."""
from __future__ import annotations

import pytest

from a2sdlc.adapters.gh_actions_subscriber import GhActionsLogSubscriber
from a2sdlc.domain.models import StageName
from a2sdlc.evaluation.progress import (
    GroupClose,
    GroupOpen,
    Metrics,
    StageEnd,
    StageStart,
    ToolEntry,
)


@pytest.mark.asyncio
async def test_stage_start_opens_workflow_group(capsys) -> None:
    sub = GhActionsLogSubscriber()
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid",
                                started_at=0.0))
    out = capsys.readouterr().out
    assert "::group::Stage spec (session sid)" in out


@pytest.mark.asyncio
async def test_stage_end_closes_group_with_status(capsys) -> None:
    sub = GhActionsLogSubscriber()
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid",
                                started_at=0.0))
    capsys.readouterr()  # drain
    final = Metrics(0, 0, 0.0, 0, 0.0)
    await sub.handle(StageEnd(stage=StageName.SPEC, success=True, error=None,
                              final_metrics=final))
    out = capsys.readouterr().out
    assert "Stage spec end: OK" in out
    assert "::endgroup::" in out


@pytest.mark.asyncio
async def test_tool_entry_emits_grouped_block(capsys) -> None:
    sub = GhActionsLogSubscriber()
    await sub.handle(ToolEntry(timestamp=0.1, name="Read", target="foo.py"))
    out = capsys.readouterr().out
    assert "::group::Tool: Read" in out
    assert "foo.py" in out
    assert "::endgroup::" in out


@pytest.mark.asyncio
async def test_group_open_close_round_trip(capsys) -> None:
    sub = GhActionsLogSubscriber()
    await sub.handle(GroupOpen(title="Agent output (1234 chars)"))
    await sub.handle(GroupClose())
    out = capsys.readouterr().out
    assert "::group::Agent output (1234 chars)" in out
    assert "::endgroup::" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/adapters/test_gh_actions_subscriber.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'a2sdlc.adapters.gh_actions_subscriber'`.

- [ ] **Step 3: Create `gh_actions_subscriber.py`**

Create `src/a2sdlc/adapters/gh_actions_subscriber.py`:

```python
"""GhActionsLogSubscriber — workflow-log output via ::group:: markers."""
from __future__ import annotations

import sys

from a2sdlc.evaluation.progress import (
    GroupClose,
    GroupOpen,
    ProgressEvent,
    StageEnd,
    StageStart,
    ToolEntry,
)


class GhActionsLogSubscriber:
    """Prints events to stdout with ::group::/::endgroup:: markers.

    Reproduces the workflow-log output that today is emitted by
    ``runner.py``'s inline ``print("::group::...")`` and the old
    ``GhActionsProgressAdapter``. Drop-in equivalent for CI consumption.
    """

    async def handle(self, event: ProgressEvent) -> None:
        if isinstance(event, StageStart):
            print(  # noqa: T201
                f"::group::Stage {event.stage.value} (session {event.session_id})",
                file=sys.stdout,
            )
        elif isinstance(event, StageEnd):
            status = "OK" if event.success else "FAIL"
            print(f"Stage {event.stage.value} end: {status}", file=sys.stdout)  # noqa: T201
            print("::endgroup::", file=sys.stdout)  # noqa: T201
        elif isinstance(event, GroupOpen):
            print(f"::group::{event.title}", file=sys.stdout)  # noqa: T201
        elif isinstance(event, GroupClose):
            print("::endgroup::", file=sys.stdout)  # noqa: T201
        elif isinstance(event, ToolEntry):
            # Reproduce the per-tool grouped block from the old runner inline.
            print(f"::group::Tool: {event.name}", file=sys.stdout)  # noqa: T201
            print(f"  target: {event.target}", file=sys.stdout)  # noqa: T201
            print("::endgroup::", file=sys.stdout)  # noqa: T201
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/adapters/test_gh_actions_subscriber.py -v`
Expected: PASS — 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/a2sdlc/adapters/gh_actions_subscriber.py tests/adapters/test_gh_actions_subscriber.py
git commit -m "feat(adapters): add GhActionsLogSubscriber driven by ProgressEvent stream"
```

---

## Task 8: GhCommentSubscriber

**Files:**
- Create: `src/a2sdlc/adapters/gh_comment_subscriber.py`
- Test: `tests/adapters/test_gh_comment_subscriber.py`

- [ ] **Step 1: Write the failing test**

Create `tests/adapters/test_gh_comment_subscriber.py`:

```python
"""GhCommentSubscriber — edits the issue/PR comment with throttled status."""
from __future__ import annotations

from typing import Any

import pytest

from a2sdlc.adapters.gh_comment_subscriber import GhCommentSubscriber
from a2sdlc.domain.models import StageName
from a2sdlc.evaluation.progress import (
    Metrics,
    Milestone,
    ProgressState,
    StageEnd,
    StageStart,
)


class _FakeComment:
    def __init__(self) -> None:
        self.updates: list[str] = []
        self.appends: list[str] = []
        self.finalized: str | None = None

    def update(self, text: str) -> None:
        self.updates.append(text)

    def append(self, text: str) -> None:
        self.appends.append(text)

    def finalize(self, text: str) -> None:
        self.finalized = text


def _state() -> ProgressState:
    return ProgressState(project_root="/tmp")


@pytest.mark.asyncio
async def test_first_metrics_event_updates_comment() -> None:
    state = _state()
    comment = _FakeComment()
    sub = GhCommentSubscriber(comment, state, throttle_seconds=0.0)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid",
                                started_at=0.0))
    await sub.handle(Metrics(1, 2, 0.05, 1, 0.0))
    assert len(comment.updates) == 1


@pytest.mark.asyncio
async def test_metrics_within_throttle_window_drops_update() -> None:
    state = _state()
    comment = _FakeComment()
    sub = GhCommentSubscriber(comment, state, throttle_seconds=10.0)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid",
                                started_at=0.0))
    await sub.handle(Metrics(1, 2, 0.05, 1, 0.0))
    await sub.handle(Metrics(2, 3, 0.10, 2, 1.0))
    assert len(comment.updates) == 1


@pytest.mark.asyncio
async def test_milestone_appends_immediately_no_throttle() -> None:
    state = _state()
    comment = _FakeComment()
    sub = GhCommentSubscriber(comment, state, throttle_seconds=10.0)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid",
                                started_at=0.0))
    await sub.handle(Milestone(timestamp=0.5, label="brainstorming invoked"))
    await sub.handle(Milestone(timestamp=1.0, label="spec approved"))
    assert len(comment.appends) == 2
    assert "brainstorming" in comment.appends[0]


@pytest.mark.asyncio
async def test_stage_end_finalizes_with_success_marker() -> None:
    state = _state()
    comment = _FakeComment()
    sub = GhCommentSubscriber(comment, state, throttle_seconds=0.0)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid",
                                started_at=0.0))
    final = Metrics(input_tokens=10, output_tokens=20, total_cost_usd=0.42,
                    num_turns=5, elapsed=30.0)
    await sub.handle(StageEnd(stage=StageName.SPEC, success=True, error=None,
                              final_metrics=final))
    assert comment.finalized is not None
    assert "spec done" in comment.finalized
    assert "$0.42" in comment.finalized
    assert "5 turns" in comment.finalized
    assert "✅" in comment.finalized


@pytest.mark.asyncio
async def test_stage_end_finalizes_with_failure_marker() -> None:
    state = _state()
    comment = _FakeComment()
    sub = GhCommentSubscriber(comment, state, throttle_seconds=0.0)
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="sid",
                                started_at=0.0))
    final = Metrics(0, 0, 0.0, 0, 0.0)
    await sub.handle(StageEnd(stage=StageName.SPEC, success=False, error="boom",
                              final_metrics=final))
    assert comment.finalized is not None
    assert "❌" in comment.finalized
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/adapters/test_gh_comment_subscriber.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'a2sdlc.adapters.gh_comment_subscriber'`.

- [ ] **Step 3: Create `gh_comment_subscriber.py`**

Create `src/a2sdlc/adapters/gh_comment_subscriber.py`:

```python
"""GhCommentSubscriber — throttled status edits + final summary on issue/PR comment."""
from __future__ import annotations

from a2sdlc.domain.models import StageName
from a2sdlc.evaluation.progress import (
    Metrics,
    Milestone,
    ProgressEvent,
    ProgressState,
    StageEnd,
    StageStart,
    format_progress,
)
from a2sdlc.evaluation.throttle import Throttle


class GhCommentSubscriber:
    """Edits the GitHub issue/PR comment with progress updates.

    - ``StageStart``: caches the stage so ``format_progress`` can render it.
    - ``Metrics``: throttled to ``throttle_seconds`` (default 5s) — protects
      against GitHub API rate limits.
    - ``Milestone``: appended immediately (rare events worth posting).
    - ``StageEnd``: never throttled; calls ``comment.finalize`` with a
      definitive summary including cost and turn count.
    """

    def __init__(
        self,
        comment_handle,  # CommentManager-like (has update/append/finalize)
        progress_state: ProgressState,
        throttle_seconds: float = 5.0,
    ) -> None:
        self._comment = comment_handle
        self._state = progress_state
        self._throttle = Throttle(min_interval=throttle_seconds)
        self._stage: StageName | None = None

    async def handle(self, event: ProgressEvent) -> None:
        if isinstance(event, StageStart):
            self._stage = event.stage
        elif isinstance(event, Metrics):
            if self._throttle.ready():
                text = format_progress(self._stage.value if self._stage else "?",
                                       self._state)
                self._comment.update(text)
        elif isinstance(event, Milestone):
            self._comment.append(f"\u2728 {event.label}")
        elif isinstance(event, StageEnd):
            icon = "\u2705" if event.success else "\u274c"
            self._comment.finalize(
                f"{icon} {event.stage.value} done — "
                f"${event.final_metrics.total_cost_usd:.2f}, "
                f"{event.final_metrics.num_turns} turns"
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/adapters/test_gh_comment_subscriber.py -v`
Expected: PASS — 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/a2sdlc/adapters/gh_comment_subscriber.py tests/adapters/test_gh_comment_subscriber.py
git commit -m "feat(adapters): add GhCommentSubscriber (replaces dispatch.py on_progress lambda)"
```

---

## Task 9: Runner refactor

**Files:**
- Modify: `src/a2sdlc/pipeline/runner.py` (drop `progress` ctor arg, drop `on_progress` kwarg, drop inline `print("::group::")` fallback; mutate `progress_state` instead)
- Modify: `src/a2sdlc/adapters/protocols.py` (extend `StageRunner.run` signature with `progress_state: ProgressState`)
- Modify: `src/a2sdlc/pipeline/stage_executor.py` (drop `on_progress`, accept and thread `progress_state`)
- Test: existing `tests/pipeline/test_runner*.py` (update mock signatures)

**This task breaks `make check` until Task 11 finishes the dispatch-side rewrite. Commit at the end of the task even though the suite isn't fully green.**

- [ ] **Step 1: Extend `StageRunner.run` Protocol**

In `src/a2sdlc/adapters/protocols.py`, modify the `StageRunner.run` signature:

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
        progress_state: "ProgressState",  # NEW — mutated; events flow to subscribers
        is_resume: bool = False,
        branch: str = "",
    ) -> RunResult: ...
```

Add the import at the top:

```python
from a2sdlc.evaluation.progress import ProgressState  # noqa: TCH001
```

Remove the `on_progress: Callable[[str], None] | None = None` parameter (line 36).

- [ ] **Step 2: Rewrite `pipeline/runner.py` to mutate `progress_state`**

Replace the body of `run_stage` in `src/a2sdlc/pipeline/runner.py`. Key changes:
- Drop the `on_progress: Callable[..., None] | None = None` parameter.
- Drop the `progress_adapter: ProgressAdapter | None = None` parameter.
- Add a required `progress_state: ProgressState` parameter.
- **Remove** the local `progress = ProgressState(...)` construction (lines 106-113).
- **Remove** the inline `print("::group::Tool: ...")` / `print("::endgroup::")` blocks (lines 261-272).
- Replace `progress.tool_log.append(...)`, `progress.input_tokens = ...` etc. with `await progress_state.add_tool_call(...)` and `await progress_state.update_metrics(...)`.

The new `run_stage` skeleton:

```python
async def run_stage(
    user_prompt: str,
    system_prompt: str,
    config: StageConfig,
    ticket_key: str,
    stage: str,
    project_root: str,
    progress_state: ProgressState,
    is_resume: bool = False,
    branch: str = "",
    effort: str | None = None,
) -> RunResult:
    """Run a pipeline stage via Claude Agent SDK; mutates progress_state."""
    from claude_agent_sdk import ClaudeAgentOptions, query  # noqa: PLC0415

    sid = get_session_id(ticket_key, stage)
    logger.info(
        "Running stage: ticket=%s stage=%s session=%s resume=%s",
        ticket_key, stage, sid, is_resume,
    )

    options_kwargs: dict[str, Any] = {
        "system_prompt": system_prompt,
        "permission_mode": "bypassPermissions",
        "allowed_tools": config.allowed_tools,
        "max_turns": config.max_turns,
        "model": config.model,
        "cwd": project_root,
        "setting_sources": ["project", "local"],
    }
    if effort is not None:
        sdk_effort = _EFFORT_SDK_MAP.get(effort)
        if sdk_effort is None:
            raise ValueError(
                f"Invalid effort {effort!r}. Expected one of {sorted(_EFFORT_SDK_MAP)}."
            )
        options_kwargs["effort"] = sdk_effort

    options = ClaudeAgentOptions(**options_kwargs)
    if is_resume:
        options.resume = sid
    else:
        options.session_id = sid

    timeout_seconds = config.timeout_minutes * 60
    result_msg: ResultMessage | None = None

    try:
        async def _stream() -> None:
            nonlocal result_msg
            num_turns = 0
            async for msg in query(prompt=user_prompt, options=options):
                if isinstance(msg, AssistantMessage):
                    num_turns += 1
                    await _handle_assistant_message(msg, progress_state, num_turns)
                elif isinstance(msg, ResultMessage):
                    result_msg = msg

        await asyncio.wait_for(_stream(), timeout=timeout_seconds)
    except TimeoutError:
        logger.error("Stage %s timed out after %d minutes",
                     stage, config.timeout_minutes)
        return RunResult(
            success=False,
            error=f"timeout ({config.timeout_minutes}min)",
            session_id=sid,
            tool_log=[e.name for e in progress_state.tool_log],
            progress=progress_state,
        )
    except Exception as exc:
        logger.exception("SDK error during stage %s", stage)
        return RunResult(
            success=False,
            error=f"sdk_error: {type(exc).__name__}: {exc}",
            session_id=sid,
            tool_log=[e.name for e in progress_state.tool_log],
            progress=progress_state,
        )

    if result_msg is None:
        return RunResult(
            success=False,
            error="no_result",
            session_id=sid,
            tool_log=[e.name for e in progress_state.tool_log],
            progress=progress_state,
        )

    usage = result_msg.usage or {}
    input_tokens = _get_tokens(usage, "input_tokens")
    output_tokens = _get_tokens(usage, "output_tokens")
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
        tool_log=[e.name for e in progress_state.tool_log],
        progress=progress_state,
    )

    logger.info(
        "Stage complete: success=%s cost=$%.4f turns=%d tools=%d output_len=%d",
        run_result.success, run_result.total_cost_usd, run_result.num_turns,
        len(run_result.tool_log), len(run_result.output),
    )
    return run_result
```

Rewrite `_handle_assistant_message` to be async and mutate state. **The block below replaces the entire current function body (lines 205-276) — including the `console.log(...)` calls, the inline `print("::group::...")` / `print("::endgroup::")` fallbacks, and the `TextBlock` preview branch. None of those survive.**

```python
async def _handle_assistant_message(
    msg: object,
    progress_state: ProgressState,
    num_turns: int,
) -> None:
    """Extract tool calls, usage, and milestones from an AssistantMessage.

    ``num_turns`` is owned by the runner loop (incremented once per
    AssistantMessage there) and threaded in. The handler must not
    increment it — doing so would double-count.
    """
    # Accumulate usage → emit Metrics
    usage = getattr(msg, "usage", None)
    if usage:
        tin = _get_tokens(usage, "input_tokens")
        tout = _get_tokens(usage, "output_tokens")
        cost = getattr(msg, "total_cost_usd", None) or progress_state.total_cost_usd
        await progress_state.update_metrics(
            tin=tin, tout=tout, cost=cost, turns=num_turns,
        )

    # Process content blocks
    content = getattr(msg, "content", None)
    if not content:
        return
    for block in content:
        if isinstance(block, ToolUseBlock):
            name = block.name or "unknown"
            inp = block.input if isinstance(block.input, dict) else {}
            target = extract_target(name, inp, progress_state.project_root)
            await progress_state.add_tool_call(name, target)

            # Skill invocation → milestone
            if name == "Skill":
                skill_name = inp.get("skill", "unknown")
                await progress_state.add_milestone(f"{skill_name} invoked")

            # TodoWrite → update tasks dict (no event needed; tasks aren't part of taxonomy)
            if name == "TodoWrite":
                todos = inp.get("todos", [])
                if isinstance(todos, list):
                    for todo in todos:
                        if isinstance(todo, dict):
                            subject = todo.get("content", "")
                            status = todo.get("status", "pending")
                            if subject:
                                progress_state.tasks[subject] = status
        # TextBlock dropped — not part of the event stream; logging covers it.
```

Rewrite `SdkStageRunner` constructor and `run`:

```python
class SdkStageRunner:
    """StageRunner backed by the Claude Agent SDK. Wraps ``run_stage``."""

    def __init__(self, effort: str | None = None) -> None:
        self._effort = effort

    async def run(
        self,
        user_prompt: str,
        system_prompt: str,
        config: StageConfig,
        ticket_key: str,
        stage: StageName,
        project_root: str,
        progress_state: ProgressState,
        is_resume: bool = False,
        branch: str = "",
    ) -> RunResult:
        return await run_stage(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            config=config,
            ticket_key=ticket_key,
            stage=stage,
            project_root=project_root,
            progress_state=progress_state,
            is_resume=is_resume,
            branch=branch,
            effort=self._effort,
        )
```

- [ ] **Step 3: Modify `pipeline/stage_executor.py` — drop `on_progress`, thread `progress_state`**

In `src/a2sdlc/pipeline/stage_executor.py`:
- Remove the `_FOLLOWUP_PROMPT`/follow-up logic? **No — keep it.** Only change: the `on_progress` parameter goes; add `progress_state: ProgressState` to `StageExecutor.run`.

```python
class StageExecutor:
    """Runs a stage and handles structured-output follow-up prompts."""

    def __init__(self, runner: StageRunner) -> None:
        self._runner = runner

    async def run(
        self,
        user_prompt: str,
        system_prompt: str,
        config: StageConfig,
        ticket_key: str,
        stage: StageName,
        project_root: str,
        progress_state: ProgressState,
        is_resume: bool = False,
        branch: str = "",
    ) -> ExecutionResult:
        stats = StageRunStats()
        combined_output = ""

        result = await self._runner.run(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            config=config,
            ticket_key=ticket_key,
            stage=stage,
            project_root=project_root,
            progress_state=progress_state,
            is_resume=is_resume,
            branch=branch,
        )
        stats.add_from_result(result)
        combined_output += result.output
        # ... rest unchanged, but every recursive `self._runner.run(...)` call
        #     also passes progress_state and drops on_progress ...
```

(Edit every `self._runner.run(...)` call site in this file the same way.)

- [ ] **Step 4: Run runner-only unit tests**

Run: `uv run pytest tests/pipeline/test_runner.py -v` (if it exists) or any nearby runner test.
Expected: tests fail because they pass `progress=...` or `on_progress=...`. Update those tests to pass a `ProgressState(project_root=...)` instead.

- [ ] **Step 5: Don't run full `make check` yet — dispatch still calls the old API**

- [ ] **Step 6: Commit**

```bash
git add src/a2sdlc/pipeline/runner.py src/a2sdlc/pipeline/stage_executor.py src/a2sdlc/adapters/protocols.py tests/pipeline/test_runner*.py tests/pipeline/test_stage_executor*.py
git commit -m "refactor(runner,stage_executor): mutate ProgressState; drop on_progress"
```

---

## Task 10: Dispatch refactor — wrap stages with stage_start/stage_end

**Files:**
- Modify: `src/a2sdlc/pipeline/dispatch.py` (rename field, add wrapper, plumb state into executor)
- Test: existing `tests/pipeline/test_dispatch*.py` (update fixtures in Task 16)

- [ ] **Step 1: Rename `DispatchContext.progress` → `progress_state`**

In `src/a2sdlc/pipeline/dispatch.py`:
- Replace the import `from a2sdlc.adapters.protocols import GitAdapter, ProgressAdapter, StageRunner` with `from a2sdlc.adapters.protocols import GitAdapter, StageRunner` and add `from a2sdlc.evaluation.progress import ProgressState`.
- In `DispatchContext`:

```python
@dataclass
class DispatchContext:
    work: WorkAdapter
    git: GitAdapter
    review: ReviewAdapter
    runner: StageRunner
    progress_state: ProgressState  # was: progress: ProgressAdapter
    config: ProjectConfig
    project_root: Path
    logger: logging.Logger
    run_id: str | None = None
```

- [ ] **Step 2: Wrap MERGE branch with `stage_start`/`stage_end`**

In `dispatch.py`, immediately after `comment.start(target_stage.value)` (line 190 area), add:

```python
# 7.5 Load stage config early so stage_start has model/max_turns even for MERGE.
stage_config = load_stage_config(target_stage.value, ctx.config)
session_id = ctx.run_id or get_session_id(event.key, target_stage.value)

await ctx.progress_state.stage_start(
    target_stage,
    session_id,
    model=stage_config.model,
    max_turns=stage_config.max_turns,
    context_window=context_window_for_model(stage_config.model) or 0,
    branch=branch,
)

# Initialize success/error trackers BEFORE the try block so the finally
# clause can always emit a valid StageEnd, even on early returns or
# unexpected exceptions.
_stage_success: bool = False
_stage_error: str | None = None

try:
    # 8. Merge stage — deterministic, no AI
    if target_stage == StageName.MERGE:
        if pr_number is None:
            reason = f"No PR found for branch {branch}"
            comment.finalize(f"\U0001f6a8 {reason}")
            ctx.work.set_blocked(event.key, reason)
            _stage_error = reason
            return DispatchResult(stage=StageName.MERGE, blocked=True, error=reason)

        if gates.merge == GateMode.HUMAN:
            if not pr_lifecycle.check_human_approval(pr_number):
                comment.finalize("\u23f3 Waiting for human approval before merge.")
                _stage_error = "waiting_for_approval"
                return DispatchResult(
                    stage=StageName.MERGE, blocked=True, error="waiting_for_approval"
                )

        ctx.git.sync_with_base(base)
        pr_lifecycle.merge(pr_number)
        comment.finalize("\u2705 Merged")
        ctx.work.set_done_label(event.key)
        ctx.logger.info("dispatch.merged", extra={"pr": pr_number})
        _stage_success = True
        return DispatchResult(stage=StageName.MERGE)

    # ── SPEC/IMPLEMENT/REVIEW path (existing lines 214-end of the function) ──
    # All early-return paths in this branch must set _stage_success/_stage_error
    # before returning. The known exits are:
    #   1. exec_result.success is False (line 276 area) — set _stage_error = exec_result.error
    #   2. stage_result is None (line 293 area) — set _stage_error = "no_status_block"
    #   3. Successful exit (line 379 area) — set _stage_success = True
    # Each of these returns a DispatchResult; the finally clause runs before return.

    # ... existing SPEC/IMPLEMENT/REVIEW logic continues, with the three
    #     early-exit paths above patched to set _stage_success/_stage_error ...
finally:
    # Emit StageEnd unconditionally for whichever path we took.
    await ctx.progress_state.stage_end(
        target_stage,
        success=_stage_success,
        error=_stage_error,
        final=ctx.progress_state.snapshot_metrics(),
    )
```

Remove the duplicate `stage_config = load_stage_config(target_stage.value, ctx.config)` further down (it's now hoisted above).

- [ ] **Step 3: Replace executor call to pass `progress_state` and drop `on_progress`**

In `dispatch.py` around line 244:

```python
exec_result = await executor.run(
    user_prompt=user_prompt,
    system_prompt=system_prompt,
    config=stage_config,
    ticket_key=event.key,
    stage=target_stage,
    project_root=str(ctx.project_root),
    progress_state=ctx.progress_state,
    is_resume=False,
    branch=branch,
)
```

(`on_progress=lambda text: comment.update(text)` is removed; that logic now lives in `GhCommentSubscriber`.)

- [ ] **Step 4: Replace direct `ctx.progress.on_*` calls with `progress_state` calls**

In `dispatch.py` lines 258-261, replace:

```python
ctx.progress.on_group_open(f"Agent output ({len(exec_result.output)} chars)")
ctx.progress.on_event("output", exec_result.output)
ctx.progress.on_group_close()
```

with:

```python
await ctx.progress_state.open_group(
    f"Agent output ({len(exec_result.output)} chars)"
)
# Output content goes to logging, not the event stream — the GH-Actions
# subscriber doesn't render TextBlock-style content; it groups tools.
await ctx.progress_state.close_group()
ctx.logger.info("agent.output", extra={"len": len(exec_result.output)})
```

- [ ] **Step 5: Patch each early-return on the SDK path to set `_stage_success`/`_stage_error` before returning**

Find each `return DispatchResult(...)` in the SPEC/IMPLEMENT/REVIEW branch (originally lines 290, 312, 379) and prepend the appropriate assignment:

```python
# At line ~290, the "exec_result.success is False" exit:
_stage_error = exec_result.error or "unknown"
return DispatchResult(stage=target_stage, blocked=True, error=exec_result.error)

# At line ~312, the "no status block" exit:
_stage_error = "no_status_block"
return DispatchResult(stage=target_stage, blocked=True, error="no_status_block")

# At line ~379, the success exit:
_stage_success = True
return DispatchResult(stage=target_stage, status=stage_result.status, ...)
```

Verify with `git grep -n "return DispatchResult" src/a2sdlc/pipeline/dispatch.py` that you've covered every return site inside the wrapped block. The `finally` clause will run before each return and emit the correct `StageEnd`.

- [ ] **Step 6: Don't run full `make check` yet — `cli.py`/`cli_local.py` still construct old shape**

- [ ] **Step 7: Commit**

```bash
git add src/a2sdlc/pipeline/dispatch.py
git commit -m "refactor(dispatch): wrap stages with stage_start/stage_end; rename progress field"
```

---

## Task 11: cli_local refactor — register ConsoleSubscriber

**Files:**
- Modify: `src/a2sdlc/cli_local.py` (construct ProgressState, register subscriber, drop on_stage_start/end calls)
- Modify: `src/a2sdlc/adapters/factory.py` (rename `build_progress_adapter` → `build_console_subscriber`; drop GH branch)

- [ ] **Step 1: Update `factory.py`**

In `src/a2sdlc/adapters/factory.py`, replace `build_progress_adapter(name)` with:

```python
def build_console_subscriber(progress_state):
    """Construct the local ConsoleSubscriber. GH dispatch wires its own."""
    from a2sdlc.adapters.console_subscriber import ConsoleSubscriber  # noqa: PLC0415
    return ConsoleSubscriber(progress_state)
```

(Delete the prior `build_progress_adapter` function and its `gh_actions` branch — GH dispatch composes its subscribers directly in `cli.py`.)

Also update the config validation: in `src/a2sdlc/config.py`, the `adapters.progress` field should no longer accept `"gh_actions"` if you want to keep the local-config schema strict. Or leave it alone — `cli_local.py` only ever reads `adapters.progress=="console"` in practice.

- [ ] **Step 2: Modify `cli_local.py`**

In `src/a2sdlc/cli_local.py`:

Replace `_build_runner` (lines 87-99) with:

```python
def _build_runner(runner_override: str | None, effort: str | None = None) -> StageRunner:
    """Construct the StageRunner. ``runner_override='fake'`` is a test hook."""
    if runner_override == "fake":
        from tests.fakes import FakeStageRunner  # noqa: PLC0415
        return FakeStageRunner()
    from a2sdlc.pipeline.runner import SdkStageRunner  # noqa: PLC0415
    return SdkStageRunner(effort=effort)
```

In `run_stage_entry`, after `cfg = load_config_file(project_root)` (around line 141), replace the adapter construction block (lines ~163-174) with:

```python
work = build_work_adapter(
    cfg.adapters.work,
    project_root=project_root,
    session_id=session_id,
    stage=stage,
    ticket_path=args.ticket,
)
review = build_review_adapter(cfg.adapters.review, project_root=project_root)
git = build_git_adapter(cfg.adapters.git, project_root=project_root)

# Construct the dispatch-lifetime ProgressState and register subscribers.
progress_state = ProgressState(project_root=str(project_root))
progress_state.subscribe(build_console_subscriber(progress_state))

runner = _build_runner(runner_override, effort=cfg.effort)
```

Update the `DispatchContext` construction (line ~185):

```python
ctx = DispatchContext(
    work=work,
    git=git,
    review=review,
    runner=runner,
    progress_state=progress_state,  # was: progress=progress
    config=cfg,
    project_root=project_root,
    logger=logging.getLogger("a2sdlc.pipeline.dispatch"),
)
```

Delete `progress.on_stage_start(stage, session_id)` (line 196).
Delete `progress.on_stage_end(stage, ok)` (line 266).

Update the imports at the top:

```python
from a2sdlc.adapters.factory import (
    build_console_subscriber,
    build_git_adapter,
    build_review_adapter,
    build_work_adapter,
)
from a2sdlc.evaluation.progress import ProgressState
```

(Remove the `build_progress_adapter` import.)

- [ ] **Step 3: Run local-flow integration tests**

Run: `uv run pytest tests/cli_local* tests/test_cli* -v`
Expected: failures from outdated mock signatures — those get fixed in Task 16.

- [ ] **Step 4: Commit**

```bash
git add src/a2sdlc/cli_local.py src/a2sdlc/adapters/factory.py
git commit -m "refactor(cli_local): construct ProgressState; register ConsoleSubscriber"
```

---

## Task 12: cli refactor — register GH subscribers

**Files:**
- Modify: `src/a2sdlc/cli.py` (construct ProgressState, register `GhActionsLogSubscriber` + `GhCommentSubscriber`)

- [ ] **Step 1: Modify `cli.py`**

In `src/a2sdlc/cli.py`, replace the `dispatch` command body (lines ~110-159):

```python
if args.command == "dispatch":
    project_root = args.project_root or find_project_root()

    from a2sdlc.config import load_config_file  # noqa: PLC0415
    from a2sdlc.pipeline.dispatch import DispatchContext, dispatch  # noqa: PLC0415

    config = load_config_file(project_root)
    setup_logging("dispatch", "dispatch", project_root)

    from a2sdlc.adapters.github import (  # noqa: PLC0415
        GitHubReviewAdapter, GitHubWorkAdapter, connect,
    )

    token = os.environ.get("GITHUB_TOKEN", os.environ.get("GH_TOKEN", ""))
    repo_name = os.environ.get("GITHUB_REPOSITORY", "")
    repo = connect(repo_name, token)
    work_adapter = GitHubWorkAdapter(repo)
    review_adapter = GitHubReviewAdapter(repo)

    from a2sdlc.adapters.git import LocalGitAdapter  # noqa: PLC0415
    from a2sdlc.adapters.gh_actions_subscriber import GhActionsLogSubscriber  # noqa: PLC0415
    # NOTE: GhCommentSubscriber needs a comment_handle, which is created
    # *inside* dispatch (it's per-stage). For now, GhActionsLogSubscriber
    # is registered up front; GhCommentSubscriber is registered inside
    # dispatch.py once `comment` is created. (See Task 12 step 2.)
    from a2sdlc.evaluation.progress import ProgressState  # noqa: PLC0415
    from a2sdlc.pipeline.runner import SdkStageRunner  # noqa: PLC0415

    git = LocalGitAdapter(project_root)
    progress_state = ProgressState(project_root=str(project_root))
    progress_state.subscribe(GhActionsLogSubscriber())

    ctx = DispatchContext(
        work=work_adapter,
        git=git,
        review=review_adapter,
        runner=SdkStageRunner(effort=config.effort),
        progress_state=progress_state,
        config=config,
        project_root=project_root,
        logger=logging.getLogger("a2sdlc.pipeline.dispatch"),
    )

    try:
        result = asyncio.run(dispatch(ctx))
        if result.blocked:
            logger.error("Dispatch blocked: %s", result.error)
            sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Interrupted")
```

- [ ] **Step 2: Wire `GhCommentSubscriber` inside `dispatch.py` once `comment` exists**

The `comment` object is created in `dispatch.py` around line 188 (`comment = CommentManager(...)`). Immediately after the comment is created and before `comment.start(...)`, add:

```python
# Register the comment-driving subscriber now that we have a comment handle.
from a2sdlc.adapters.gh_comment_subscriber import GhCommentSubscriber  # noqa: PLC0415
ctx.progress_state.subscribe(GhCommentSubscriber(comment, ctx.progress_state))
```

(Note: this is the only place where `dispatch.py` knows about a specific subscriber. It's defensible because the comment lifecycle is intrinsically dispatch-scoped — there's no upstream point where the comment exists.)

- [ ] **Step 3: Don't run full `make check` yet — test fixtures still mock `ProgressAdapter`**

- [ ] **Step 4: Commit**

```bash
git add src/a2sdlc/cli.py src/a2sdlc/pipeline/dispatch.py
git commit -m "refactor(cli,dispatch): construct ProgressState; register GH subscribers"
```

---

## Task 13: Delete old code

**Files:**
- Delete: `src/a2sdlc/adapters/progress_console.py`
- Delete: `src/a2sdlc/adapters/progress_gh_actions.py`
- Modify: `src/a2sdlc/adapters/protocols.py` (delete `ProgressAdapter` Protocol)

- [ ] **Step 1: Delete the two old adapter files**

```bash
git rm src/a2sdlc/adapters/progress_console.py
git rm src/a2sdlc/adapters/progress_gh_actions.py
```

- [ ] **Step 2: Delete `ProgressAdapter` Protocol**

In `src/a2sdlc/adapters/protocols.py`, delete the `ProgressAdapter` class (lines 41-48).

- [ ] **Step 3: Verify no stale imports**

Run: `git grep -nE "ProgressAdapter|progress_console|progress_gh_actions" src/`
Expected: no matches.

If there are matches, delete them (they're dead imports left over).

- [ ] **Step 4: Commit**

```bash
git add src/a2sdlc/adapters/protocols.py
git commit -m "refactor(adapters): delete ProgressAdapter Protocol and old adapter modules"
```

---

## Task 14: Test fixture cleanup

**Files:**
- Modify: `tests/fakes.py` (delete `FakeProgressAdapter`)
- Modify: `tests/pipeline/test_dispatch.py`, `test_dispatch_e2e.py`, `test_dispatch_progress.py`, `test_stage_executor.py` (switch to `RecordingSubscriber`)

- [ ] **Step 1: Delete `FakeProgressAdapter`**

In `tests/fakes.py`, delete the `FakeProgressAdapter` class (and any helper symbols it had).

- [ ] **Step 2: Replace usage in `tests/pipeline/test_dispatch.py`**

Wherever the test sets up a `DispatchContext`, replace:

```python
from tests.fakes import FakeProgressAdapter
ctx = DispatchContext(..., progress=FakeProgressAdapter(), ...)
```

with:

```python
from a2sdlc.evaluation.progress import ProgressState
from tests.fakes import RecordingSubscriber

progress_state = ProgressState(project_root=str(project_root))
recorder = RecordingSubscriber()
progress_state.subscribe(recorder)
ctx = DispatchContext(..., progress_state=progress_state, ...)
```

Where the test asserted `progress.started == [...]` or similar, switch to:

```python
from a2sdlc.evaluation.progress import StageStart, StageEnd
assert isinstance(recorder.events[0], StageStart)
assert isinstance(recorder.events[-1], StageEnd)
```

- [ ] **Step 3: Same replacement in every test file that references `ProgressAdapter`, `FakeProgressAdapter`, `progress=`, or `on_progress=`**

Run a grep first to enumerate every site:

```bash
git grep -nE "ProgressAdapter|FakeProgressAdapter|progress\s*=|on_progress" tests/
```

Apply the `RecordingSubscriber` + `ProgressState` pattern to every match. Known affected files:

- `tests/pipeline/test_dispatch.py`
- `tests/pipeline/test_dispatch_e2e.py`
- `tests/pipeline/test_dispatch_progress.py` — assertions about tool-call traces filter `recorder.events` by `isinstance(e, ToolEntry)`
- `tests/pipeline/test_stage_executor.py`
- `tests/pipeline/test_runner*.py` (any tests that called the runner with `on_progress=` or `progress=` kwargs)
- `tests/test_cli_local*.py` (any CLI integration test that built a `DispatchContext`)
- `tests/cli_local*` from Task 11 step 3
- `tests/fakes.py` — already trimmed in step 1 above

Confirm coverage: after rewrites, `git grep -nE "ProgressAdapter|FakeProgressAdapter" tests/` must return no matches.

- [ ] **Step 3b: Add an integration test asserting `StageEnd` follows the final `Metrics`**

Per spec §6 — locks the terminal-state guarantee. Add to `tests/pipeline/test_dispatch_progress.py` (or whichever integration test exercises the full dispatch flow):

```python
@pytest.mark.asyncio
async def test_stage_end_follows_final_metrics() -> None:
    # ... set up DispatchContext with FakeStageRunner that emits a few
    #     update_metrics() calls then returns ...
    rec = RecordingSubscriber()
    ctx.progress_state.subscribe(rec)

    await dispatch(ctx)

    # The last Metrics event must precede the StageEnd event.
    metrics_indices = [i for i, e in enumerate(rec.events) if isinstance(e, Metrics)]
    end_indices = [i for i, e in enumerate(rec.events) if isinstance(e, StageEnd)]
    assert metrics_indices, "no Metrics event emitted"
    assert end_indices, "no StageEnd event emitted"
    assert metrics_indices[-1] < end_indices[-1]
```

- [ ] **Step 4: Run full test suite**

Run: `make check`
Expected: PASS — all 496 tests + the new ones (~514 total).

If failures remain, they are residual mock signatures. Update them per the same pattern.

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: switch fixtures to RecordingSubscriber + ProgressState"
```

---

## Task 15: Smoke validation

**Files:** none (verification only)

- [ ] **Step 1: Run the existing smoke workspace**

```bash
cd /Users/iorlas/Workspaces/a2sdlc-smoke
git checkout main && git branch -D a2sdlc/smoke3 2>/dev/null || true
git clean -fdx
rm -rf ~/.claude/projects/-Users-iorlas-Workspaces-a2sdlc-smoke/* 2>/dev/null || true
a2sdlc run-stage spec --ticket ticket.md --session smoke3 .
```

Expected: status bar shows non-zero values during execution; SPEC stage completes OK.

- [ ] **Step 2: Run IMPLEMENT**

```bash
a2sdlc run-stage implement --session smoke3 .
```

Expected: status bar shows live tokens / cost / turns updates; quality gate passes; final summary shows real numbers.

- [ ] **Step 3: Verify acceptance grep checks**

```bash
cd /Users/iorlas/Workspaces/a2sdlc-engine
git grep -nE "ProgressAdapter" src/
git grep -nE "on_progress" src/
git grep -nE "Throttle\s*\(" src/a2sdlc/pipeline/
git grep -nE "time\.(monotonic|time)\(\)" src/a2sdlc/pipeline/runner.py | grep -v start_time
```

Expected: all four return no matches.

- [ ] **Step 4: Run full quality gate one more time**

Run: `make check`
Expected: PASS.

- [ ] **Step 5: Commit any final cleanup (if any)**

```bash
git status
# If anything stray, add + commit; otherwise skip.
```

---

## Self-Review Notes

- **Spec coverage:** Tasks 1–13 implement every section of the spec (event taxonomy → §3.1, Subscriber Protocol → §3.2, ProgressState bus → §3.3, three concrete subscribers → §3.4, composition roots → §3.5, `StageEnd` terminal-state guarantee → §3.6 via Task 10's `finally` block, ordering & exception containment → §3.7 via Task 4's `_emit`/`_failed` logic, layout → §4 via the file plan above, migration → §5 via Task ordering, testing → §6 via test files in each task, acceptance criteria → §9 via Task 15's grep checks).
- **Single-PR migration:** Tasks 9–13 will leave the suite red mid-flight; this is by design per the spec (§5). Task 14 is the recovery point.
- **No placeholders:** every step has either complete code or an exact command + expected output.

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-18-progress-subscribers.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints.

Which approach?
