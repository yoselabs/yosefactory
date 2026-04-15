# Feedback-Aware Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the a2sdlc pipeline to collect and route human/AI feedback via @mention-gated comments, using handover comments as inter-stage contracts.

**Architecture:** The engine's dispatch loop is extended to handle comment/review events alongside label events. A handover-based context assembly replaces per-stage custom prompt building. Feedback is collected from both issue and PR comments, routed to the appropriate stage via a deterministic routing table. The `proceed` label becomes context-dependent (advance past whichever gate the pipeline is blocked at).

**Tech Stack:** Python 3.12, Pydantic, PyGithub, pytest, dataclasses

**Spec:** `docs/superpowers/specs/2026-04-15-feedback-aware-pipeline-design.md`

---

## File Structure

### New files
- `src/a2sdlc/handover.py` — handover pattern regex, comment parsing, `HandoverComment` and `FeedbackItem` dataclasses
- `src/a2sdlc/context_assembly.py` — uniform context builder (find handover, collect feedback, build prompt)
- `src/a2sdlc/feedback_routing.py` — routing table: current stage → target stage for feedback events
- `tests/test_handover.py` — handover pattern matching, comment parsing
- `tests/test_context_assembly.py` — context assembly from handovers + feedback
- `tests/test_feedback_routing.py` — routing table tests

### Modified files
- `src/a2sdlc/models.py` — remove `GateConfig.review`, add `GateConfig.spec`; clean `StageResult`
- `src/a2sdlc/config.py` — update `load_config_file` for new gate shape + trigger.mention config
- `src/a2sdlc/adapters/work.py` — new `PipelineEvent` shape (trigger_stage, is_feedback); new protocol methods
- `src/a2sdlc/adapters/review.py` — new `collect_pr_feedback` and `find_last_handover` protocol methods
- `src/a2sdlc/adapters/github.py` — implement new protocol methods; extend `parse_event` for comment/review events
- `src/a2sdlc/stages/__init__.py` — update `next_stage` transition table (remove review gate, add spec gate)
- `src/a2sdlc/dispatch.py` — integrate context assembly, feedback routing, dedup, proceed resolution
- `src/a2sdlc/progress.py` — update `format_final` header to include `a2sdlc:` prefix
- `tests/fakes.py` — update FakeWorkAdapter and FakeReviewAdapter for new protocol methods
- `tests/test_stages.py` — update transition table tests
- `tests/test_config.py` — test new gate/trigger config
- `tests/test_dispatch.py` — test feedback dispatch flows
- `tests/adapters/test_github_work.py` — test new event parsing
- `tests/progress/test_formatting.py` — test updated header format

---

### Task 1: Data Models — Handover & Feedback Types

**Files:**
- Create: `src/a2sdlc/handover.py`
- Test: `tests/test_handover.py`

- [ ] **Step 1: Write failing test for HANDOVER_PATTERN**

```python
# tests/test_handover.py
"""Tests for handover comment parsing and pattern matching."""

from a2sdlc.handover import HANDOVER_PATTERN, HANDOVER_PREFIX


def test_pattern_matches_all_stages():
    """Pattern compiled from StageName matches all known stages."""
    for stage in ("spec", "implement", "review", "merge"):
        text = f"### ✅ a2sdlc:{stage}"
        match = HANDOVER_PATTERN.search(text)
        assert match is not None, f"Pattern should match a2sdlc:{stage}"
        assert match.group(1) == stage


def test_pattern_rejects_unknown_stage():
    match = HANDOVER_PATTERN.search("### ✅ a2sdlc:deploy")
    assert match is None


def test_pattern_matches_in_progress_header():
    match = HANDOVER_PATTERN.search("### ⏳ a2sdlc:implement")
    assert match is not None
    assert match.group(1) == "implement"


def test_pattern_matches_error_header():
    match = HANDOVER_PATTERN.search("### 🚨 a2sdlc:review")
    assert match is not None
    assert match.group(1) == "review"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_handover.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'a2sdlc.handover'`

- [ ] **Step 3: Implement handover module**

```python
# src/a2sdlc/handover.py
"""Handover comment types and pattern matching.

The handover pattern is compiled from StageName — adding a stage
automatically updates the pattern. StageName is the single source
of truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from a2sdlc.models import StageName

# ── Handover pattern ─────────────────────────────────────────────

HANDOVER_PREFIX = "a2sdlc:"
HANDOVER_PATTERN = re.compile(
    rf"{re.escape(HANDOVER_PREFIX)}({'|'.join(re.escape(s.value) for s in StageName)})"
)

# ── Stage ordering for tie-breaking ──────────────────────────────

_STAGE_ORDER: dict[StageName, int] = {s: i for i, s in enumerate(StageName)}


def later_stage(a: StageName, b: StageName) -> StageName:
    """Return whichever stage comes later in the pipeline."""
    return a if _STAGE_ORDER[a] >= _STAGE_ORDER[b] else b


# ── Data types ───────────────────────────────────────────────────


@dataclass(frozen=True)
class FeedbackItem:
    """A single feedback comment from any source."""

    id: str
    author: str
    author_type: str  # "human" | "bot"
    source: str  # "issue_comment" | "pr_comment" | "pr_inline" | "pr_review"
    body: str
    file_path: str | None = None
    line_range: tuple[int, int] | None = None
    created_at: datetime = datetime.min


@dataclass(frozen=True)
class HandoverComment:
    """A parsed handover comment from an issue or PR."""

    stage: StageName
    run_id: str
    body: str
    created_at: datetime
    location: str  # "issue" | "pr"


def parse_handover(comment_body: str, comment_id: str, created_at: datetime, location: str) -> HandoverComment | None:
    """Try to parse a comment as a handover. Returns None if not a handover."""
    match = HANDOVER_PATTERN.search(comment_body)
    if match is None:
        return None
    stage = StageName(match.group(1))
    return HandoverComment(
        stage=stage,
        run_id=comment_id,
        body=comment_body,
        created_at=created_at,
        location=location,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_handover.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Write tests for parse_handover and later_stage**

```python
# Append to tests/test_handover.py
from datetime import datetime, timezone

from a2sdlc.handover import HandoverComment, parse_handover, later_stage
from a2sdlc.models import StageName


def test_parse_handover_success():
    body = "### ✅ a2sdlc:implement\n\n## Implementation Complete\n..."
    result = parse_handover(body, "c-123", datetime(2026, 4, 15, tzinfo=timezone.utc), "issue")
    assert result is not None
    assert result.stage == StageName.IMPLEMENT
    assert result.run_id == "c-123"
    assert result.location == "issue"


def test_parse_handover_not_a_handover():
    body = "Just a regular comment about the code."
    result = parse_handover(body, "c-456", datetime(2026, 4, 15, tzinfo=timezone.utc), "issue")
    assert result is None


def test_later_stage():
    assert later_stage(StageName.SPEC, StageName.IMPLEMENT) == StageName.IMPLEMENT
    assert later_stage(StageName.REVIEW, StageName.IMPLEMENT) == StageName.REVIEW
    assert later_stage(StageName.MERGE, StageName.SPEC) == StageName.MERGE
```

- [ ] **Step 6: Run all handover tests**

Run: `pytest tests/test_handover.py -v`
Expected: PASS (all 7 tests)

- [ ] **Step 7: Commit**

```bash
git add src/a2sdlc/handover.py tests/test_handover.py
git commit -m "feat: add handover types, pattern matching, and parsing"
```

---

### Task 2: Update Gate Config — Remove review, Add spec

**Files:**
- Modify: `src/a2sdlc/models.py:38-43`
- Modify: `src/a2sdlc/config.py:79-88`
- Modify: `src/a2sdlc/stages/__init__.py:35-68`
- Modify: `src/a2sdlc/dispatch.py:76-80`
- Test: `tests/test_stages.py`, `tests/test_config.py`, `tests/test_dispatch.py`

- [ ] **Step 1: Write failing test for new GateConfig shape**

```python
# Append to tests/test_models.py (or wherever GateConfig is tested)
from a2sdlc.models import GateConfig, GateMode


def test_gate_config_has_spec_and_merge():
    gates = GateConfig()
    assert gates.spec == GateMode.AUTO
    assert gates.merge == GateMode.HUMAN
    assert not hasattr(gates, "review")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py::test_gate_config_has_spec_and_merge -v`
Expected: FAIL — `gates.spec` does not exist, `gates.review` still exists

- [ ] **Step 3: Update GateConfig in models.py**

Replace `GateConfig` in `src/a2sdlc/models.py`:

```python
class GateConfig(BaseModel):
    """Gate configuration for the pipeline."""

    spec: GateMode = GateMode.AUTO
    merge: GateMode = GateMode.HUMAN
```

- [ ] **Step 4: Update config loading in config.py**

Replace gate parsing in `src/a2sdlc/config.py` (lines 79-88):

```python
    merge_mode = (
        GateMode(str(gates_raw["merge"])) if "merge" in gates_raw else GateMode.HUMAN
    )
    spec_mode = (
        GateMode(str(gates_raw["spec"])) if "spec" in gates_raw else GateMode.AUTO
    )
    gates = GateConfig(merge=merge_mode, spec=spec_mode)
```

- [ ] **Step 5: Update next_stage transition table**

Replace `next_stage` in `src/a2sdlc/stages/__init__.py`:

```python
def next_stage(
    current: StageName,
    status: StageStatus,
    gates: GateConfig,
) -> StageName | None:
    """Pure function: determine the next stage given current stage, status, and gate config.

    Transition table:
    - Spec + complete + gates.spec=AUTO → IMPLEMENT
    - Spec + complete + gates.spec=HUMAN → None (wait for human)
    - Spec + questions → None
    - Implement + complete → REVIEW (always auto, no gate)
    - Implement + questions → None
    - Review + approved + gates.merge=AUTO → MERGE
    - Review + approved + gates.merge=HUMAN → None
    - Review + changes_requested → IMPLEMENT (always loops back)
    """
    match (current, status):
        case (StageName.SPEC, StageStatus.COMPLETE):
            return StageName.IMPLEMENT if gates.spec == GateMode.AUTO else None
        case (StageName.SPEC, StageStatus.QUESTIONS):
            return None
        case (StageName.IMPLEMENT, StageStatus.COMPLETE):
            return StageName.REVIEW
        case (StageName.IMPLEMENT, StageStatus.QUESTIONS):
            return None
        case (StageName.REVIEW, StageStatus.APPROVED):
            return StageName.MERGE if gates.merge == GateMode.AUTO else None
        case (StageName.REVIEW, StageStatus.CHANGES_REQUESTED):
            return StageName.IMPLEMENT
        case _:
            return None
```

- [ ] **Step 6: Remove review gate references from dispatch.py**

In `src/a2sdlc/dispatch.py`, remove the `gate_review` directive handling (lines ~78-80). The gates construction becomes:

```python
    gates = ctx.config.gate_config()
    if directives.gate_merge is not None:
        gates = GateConfig(merge=directives.gate_merge, spec=gates.spec)
```

Also check `directives.py` — if there's a `gate_review` directive, remove it.

- [ ] **Step 7: Fix all broken tests**

Run: `make check`

Fix test failures caused by:
- Tests that reference `gates.review` — remove or update
- Tests that pass `GateConfig(review=...)` — remove the `review` param
- Tests that assert IMPLEMENT → REVIEW depends on a gate — REVIEW is now always auto

Expected: all tests pass

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: remove review gate, add spec gate — two gates only"
```

---

### Task 3: Update PipelineEvent — trigger_stage + is_feedback

**Files:**
- Modify: `src/a2sdlc/adapters/work.py:11-19`
- Modify: `tests/fakes.py` (FakeWorkAdapter)
- Test: `tests/adapters/test_github_work.py`

- [ ] **Step 1: Write failing test for new PipelineEvent shape**

```python
# tests/test_pipeline_event.py
from a2sdlc.adapters.work import PipelineEvent
from a2sdlc.models import StageName


def test_pipeline_event_feedback():
    """Feedback events have trigger_stage=None and is_feedback=True."""
    event = PipelineEvent(key="42", trigger_stage=None, is_feedback=True)
    assert event.trigger_stage is None
    assert event.is_feedback is True
    assert event.pr_number is None


def test_pipeline_event_label_trigger():
    """Label events have trigger_stage set and is_feedback=False."""
    event = PipelineEvent(key="42", trigger_stage=StageName.IMPLEMENT, is_feedback=False)
    assert event.trigger_stage == StageName.IMPLEMENT
    assert event.is_feedback is False


def test_pipeline_event_proceed():
    """Proceed label: trigger_stage=None, is_feedback=False."""
    event = PipelineEvent(key="42", trigger_stage=None, is_feedback=False)
    assert event.trigger_stage is None
    assert event.is_feedback is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_event.py -v`
Expected: FAIL — `PipelineEvent` still has `stage` not `trigger_stage`

- [ ] **Step 3: Update PipelineEvent**

Replace `PipelineEvent` in `src/a2sdlc/adapters/work.py`:

```python
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
```

- [ ] **Step 4: Add new methods to WorkAdapter protocol**

Append to `WorkAdapter` in `src/a2sdlc/adapters/work.py`:

```python
    def collect_issue_feedback(self, key: str, since: datetime) -> list[FeedbackItem]: ...
    def find_last_handover(self, key: str) -> HandoverComment | None: ...
```

Add imports at top:
```python
from datetime import datetime
from a2sdlc.handover import FeedbackItem, HandoverComment
```

- [ ] **Step 5: Add new methods to ReviewAdapter protocol**

Append to `ReviewAdapter` in `src/a2sdlc/adapters/review.py`:

```python
    def collect_pr_feedback(self, pr_number: int, since: datetime) -> list[FeedbackItem]: ...
    def find_last_handover(self, pr_number: int) -> HandoverComment | None: ...
```

Add imports at top:
```python
from datetime import datetime
from a2sdlc.handover import FeedbackItem, HandoverComment
```

- [ ] **Step 6: Update FakeWorkAdapter and FakeReviewAdapter in fakes.py**

Update `FakeWorkAdapter` to use `trigger_stage` instead of `stage`, remove `is_resume`. Add stub implementations for new methods:

```python
    def collect_issue_feedback(self, key: str, since: datetime) -> list[FeedbackItem]:
        return list(self._issue_feedback)

    def find_last_handover(self, key: str) -> HandoverComment | None:
        return self._last_handover
```

Add `_issue_feedback: list[FeedbackItem]` and `_last_handover: HandoverComment | None` to `__init__` params.

Same for `FakeReviewAdapter`:

```python
    def collect_pr_feedback(self, pr_number: int, since: datetime) -> list[FeedbackItem]:
        return list(self._pr_feedback)

    def find_last_handover(self, pr_number: int) -> HandoverComment | None:
        return self._pr_handover
```

- [ ] **Step 7: Fix all broken references**

Run: `make check`

The rename from `event.stage` → `event.trigger_stage` and `event.is_resume` → removal will break many files. Key places:
- `dispatch.py` — every reference to `event.stage` must become `event.trigger_stage`
- `github.py` — `parse_event` must return new shape
- All tests using `PipelineEvent(key=..., stage=...)` — update to `trigger_stage=...`

Do NOT update the dispatch logic yet (how it uses `trigger_stage` to decide what to run) — that's Task 6. For now, just make the rename compile: where the old code did `event.stage`, use `event.trigger_stage` and add a temporary assertion that it's not None (preserving existing behavior until the routing logic is updated).

Expected: all tests pass

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: rename PipelineEvent.stage to trigger_stage, add is_feedback"
```

---

### Task 4: Extend parse_event for Comment/Review Events

**Files:**
- Modify: `src/a2sdlc/adapters/github.py:52-148`
- Modify: `src/a2sdlc/config.py` (add trigger.mention to ProjectConfig)
- Test: `tests/adapters/test_github_work.py`

- [ ] **Step 1: Add trigger mention to ProjectConfig**

In `src/a2sdlc/config.py`, add to `ProjectConfig`:

```python
    trigger_mention: str = "@a2sdlc"
```

Update `load_config_file` to read it:

```python
    trigger_raw = pipeline.get("trigger", {})
    trigger_raw = trigger_raw if isinstance(trigger_raw, dict) else {}
    trigger_mention = str(trigger_raw.get("mention", "@a2sdlc"))
```

And pass to constructor:
```python
    config = ProjectConfig(
        ...
        trigger_mention=trigger_mention,
    )
```

- [ ] **Step 2: Write failing tests for new event types**

```python
# Append to tests/adapters/test_github_work.py

def test_parse_issue_comment_with_mention(gh_work, tmp_path):
    """Issue comment with @a2sdlc triggers feedback event."""
    event = {
        "action": "created",
        "sender": {"type": "User"},
        "issue": {"number": 42, "labels": []},
        "comment": {"body": "@a2sdlc please fix the drag and drop"},
    }
    _write_event(tmp_path, "issue_comment", event)
    result = gh_work.parse_event()
    assert result.key == "42"
    assert result.trigger_stage is None
    assert result.is_feedback is True


def test_parse_issue_comment_without_mention_skips(gh_work, tmp_path):
    """Issue comment without @a2sdlc is skipped."""
    event = {
        "action": "created",
        "sender": {"type": "User"},
        "issue": {"number": 42, "labels": []},
        "comment": {"body": "Hey @john take a look at this"},
    }
    _write_event(tmp_path, "issue_comment", event)
    with pytest.raises(SkipEvent):
        gh_work.parse_event()


def test_parse_pr_review_submitted(gh_work, tmp_path):
    """PR review submission from non-bot triggers feedback."""
    event = {
        "action": "submitted",
        "sender": {"type": "User"},
        "review": {"body": "Changes requested", "state": "changes_requested"},
        "pull_request": {"number": 7},
    }
    _write_event(tmp_path, "pull_request_review", event)
    result = gh_work.parse_event()
    assert result.key == "7"
    assert result.trigger_stage is None
    assert result.is_feedback is True
    assert result.pr_number == 7


def test_parse_pr_review_from_bot_skips(gh_work, tmp_path):
    """PR review from bot is skipped."""
    event = {
        "action": "submitted",
        "sender": {"type": "Bot"},
        "review": {"body": "Automated review"},
        "pull_request": {"number": 7},
    }
    _write_event(tmp_path, "pull_request_review", event)
    with pytest.raises(SkipEvent):
        gh_work.parse_event()


def test_parse_proceed_label(gh_work, tmp_path):
    """Proceed label creates non-feedback event with trigger_stage=None."""
    event = {
        "action": "labeled",
        "label": {"name": "proceed"},
        "issue": {"number": 42},
    }
    _write_event(tmp_path, "issues", event)
    result = gh_work.parse_event()
    assert result.key == "42"
    assert result.trigger_stage is None
    assert result.is_feedback is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/adapters/test_github_work.py -v -k "mention or pr_review or proceed_label"`
Expected: FAIL

- [ ] **Step 4: Implement new event parsing**

In `src/a2sdlc/adapters/github.py`, extend `parse_event`:

```python
    def parse_event(self) -> PipelineEvent:
        event_path = os.environ["GITHUB_EVENT_PATH"]
        event_name = os.environ["GITHUB_EVENT_NAME"]

        with open(event_path) as f:
            event = json.load(f)

        sender_type = event.get("sender", {}).get("type", "")

        if event_name == "issues":
            return self._parse_issues_event(event)
        elif event_name == "issue_comment":
            return self._parse_issue_comment_event(event, sender_type)
        elif event_name == "pull_request":
            return self._parse_pull_request_event(event)
        elif event_name == "pull_request_review":
            return self._parse_pr_review_event(event, sender_type)
        elif event_name == "pull_request_review_comment":
            return self._parse_pr_review_comment_event(event, sender_type)
        else:
            raise SkipEvent(f"unsupported event name: {event_name!r}")
```

Update `_parse_issues_event` for `proceed`:
```python
        if label_name == PROCEED_LABEL:
            return PipelineEvent(key=issue_number, trigger_stage=None, is_feedback=False)
```

New `_parse_issue_comment_event`:
```python
    def _parse_issue_comment_event(self, event: dict, sender_type: str) -> PipelineEvent:
        if sender_type == "Bot":
            raise SkipEvent("bot comment sender")

        comment_body = event.get("comment", {}).get("body", "")
        issue_number = str(event["issue"]["number"])

        # Check for trigger mention
        if self._trigger_mention not in comment_body:
            raise SkipEvent(f"comment does not contain {self._trigger_mention}")

        return PipelineEvent(
            key=issue_number,
            trigger_stage=None,
            is_feedback=True,
        )
```

New `_parse_pr_review_event`:
```python
    def _parse_pr_review_event(self, event: dict, sender_type: str) -> PipelineEvent:
        if sender_type == "Bot":
            raise SkipEvent("bot PR review sender")

        pr_number = event["pull_request"]["number"]
        return PipelineEvent(
            key=str(pr_number),
            trigger_stage=None,
            is_feedback=True,
            pr_number=pr_number,
        )
```

New `_parse_pr_review_comment_event`:
```python
    def _parse_pr_review_comment_event(self, event: dict, sender_type: str) -> PipelineEvent:
        if sender_type == "Bot":
            raise SkipEvent("bot PR review comment sender")

        comment_body = event.get("comment", {}).get("body", "")
        if self._trigger_mention not in comment_body:
            raise SkipEvent(f"PR comment does not contain {self._trigger_mention}")

        pr_number = event["pull_request"]["number"]
        return PipelineEvent(
            key=str(pr_number),
            trigger_stage=None,
            is_feedback=True,
            pr_number=pr_number,
        )
```

The `GitHubWorkAdapter.__init__` needs `trigger_mention: str = "@a2sdlc"` param stored as `self._trigger_mention`.

- [ ] **Step 5: Run all tests**

Run: `make check`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: extend parse_event for comment, PR review, and PR review comment events"
```

---

### Task 5: Feedback Routing Table

**Files:**
- Create: `src/a2sdlc/feedback_routing.py`
- Test: `tests/test_feedback_routing.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_feedback_routing.py
"""Tests for feedback routing — which stage handles feedback based on pipeline position."""

from a2sdlc.feedback_routing import resolve_target_stage
from a2sdlc.models import StageName


def test_no_stage_routes_to_spec():
    assert resolve_target_stage(current_stage=None) == StageName.SPEC


def test_spec_routes_to_spec():
    assert resolve_target_stage(current_stage=StageName.SPEC) == StageName.SPEC


def test_implement_routes_to_implement():
    assert resolve_target_stage(current_stage=StageName.IMPLEMENT) == StageName.IMPLEMENT


def test_review_routes_to_implement():
    """Review-phase feedback means 'fix the code'."""
    assert resolve_target_stage(current_stage=StageName.REVIEW) == StageName.IMPLEMENT


def test_merge_routes_to_implement():
    """Merge-gate feedback means 'fix the code'."""
    assert resolve_target_stage(current_stage=StageName.MERGE) == StageName.IMPLEMENT
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_feedback_routing.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement routing table**

```python
# src/a2sdlc/feedback_routing.py
"""Feedback routing — maps current pipeline stage to target stage for feedback events."""

from __future__ import annotations

from a2sdlc.models import StageName


def resolve_target_stage(current_stage: StageName | None) -> StageName:
    """Given the pipeline's current stage, return which stage should handle feedback.

    - No stage or SPEC: feedback is spec-level (no code exists yet)
    - IMPLEMENT or later: feedback is implementation-level (code exists, fix it)
    """
    if current_stage is None or current_stage == StageName.SPEC:
        return StageName.SPEC
    return StageName.IMPLEMENT
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_feedback_routing.py -v`
Expected: PASS (all 5)

- [ ] **Step 5: Commit**

```bash
git add src/a2sdlc/feedback_routing.py tests/test_feedback_routing.py
git commit -m "feat: add feedback routing table — current stage to target stage"
```

---

### Task 6: Handover Comment Format in progress.py

**Files:**
- Modify: `src/a2sdlc/progress.py:302-307`
- Test: `tests/progress/test_formatting.py`

- [ ] **Step 1: Write failing test**

```python
# Append to tests/progress/test_formatting.py
from a2sdlc.handover import HANDOVER_PATTERN


def test_format_final_includes_handover_marker():
    """format_final output must match HANDOVER_PATTERN for stage detection."""
    result = format_final(
        "Some output",
        stage="implement",
        stats=_fake_stats(),
        milestones=[],
        model="claude-sonnet-4-6",
        branch="agent/42",
        max_turns=25,
        context_window=200000,
    )
    assert HANDOVER_PATTERN.search(result) is not None
    assert "a2sdlc:implement" in result
```

(Use whatever `_fake_stats()` helper the test file already has, or create a minimal one.)

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/progress/test_formatting.py::test_format_final_includes_handover_marker -v`
Expected: FAIL — current header is `### ✅ implement`, not `### ✅ a2sdlc:implement`

- [ ] **Step 3: Update format_final header**

In `src/a2sdlc/progress.py`, line 302-303, change:

```python
    parts = [
        f"### \u2705 {stage}\n",
```

To:

```python
    parts = [
        f"### \u2705 a2sdlc:{stage}\n",
```

Also update `format_progress` (the in-progress header) similarly — find `⏳ **{stage}**` and change to `⏳ **a2sdlc:{stage}**`.

And `format_error` — find `🚨 **{stage}**` and change to `🚨 **a2sdlc:{stage}**`.

- [ ] **Step 4: Run all tests**

Run: `make check`
Expected: Some existing tests may assert on the exact header format — update them to include `a2sdlc:` prefix.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add a2sdlc: prefix to stage comment headers for handover detection"
```

---

### Task 7: GitHub Adapter — Feedback Collection & Handover Search

**Files:**
- Modify: `src/a2sdlc/adapters/github.py`
- Test: `tests/adapters/test_github_work.py`, `tests/adapters/test_github_review.py`

- [ ] **Step 1: Write failing tests for find_last_handover**

```python
# tests/adapters/test_github_work.py — append
def test_find_last_handover_returns_most_recent(gh_work):
    """find_last_handover returns the most recent handover comment on the issue."""
    # This test needs to mock the GitHub issue comments API.
    # Use the existing test patterns in this file for API mocking.
    # The handover comment has "### ✅ a2sdlc:implement" in its body.
    # Non-handover comments are ignored.
    pass  # Implement with real mock
```

Note: The exact test implementation depends on how the existing test file mocks PyGithub. Follow the existing patterns in `test_github_work.py`. The key assertions are:
- `find_last_handover(key)` returns `HandoverComment` for the most recent comment matching `HANDOVER_PATTERN`
- Returns `None` if no handover comments exist
- Ignores non-handover comments

- [ ] **Step 2: Implement find_last_handover on GitHubWorkAdapter**

```python
    def find_last_handover(self, key: str) -> HandoverComment | None:
        """Find the most recent handover comment on the issue."""
        issue = self._repo.get_issue(int(key))
        best: HandoverComment | None = None
        for comment in issue.get_comments():
            parsed = parse_handover(
                comment.body,
                str(comment.id),
                comment.created_at,
                "issue",
            )
            if parsed is not None:
                if best is None or parsed.created_at > best.created_at:
                    best = parsed
        return best
```

Add import: `from a2sdlc.handover import parse_handover, FeedbackItem, HandoverComment, HANDOVER_PATTERN`

- [ ] **Step 3: Implement collect_issue_feedback on GitHubWorkAdapter**

```python
    def collect_issue_feedback(self, key: str, since: datetime) -> list[FeedbackItem]:
        """Collect issue comments containing trigger mention posted after since."""
        issue = self._repo.get_issue(int(key))
        items: list[FeedbackItem] = []
        for comment in issue.get_comments(since=since):
            if self._trigger_mention not in comment.body:
                continue
            if HANDOVER_PATTERN.search(comment.body):
                continue  # Skip handover comments
            sender_type = "bot" if comment.user.type == "Bot" else "human"
            items.append(FeedbackItem(
                id=str(comment.id),
                author=comment.user.login,
                author_type=sender_type,
                source="issue_comment",
                body=comment.body,
                created_at=comment.created_at,
            ))
        return items
```

- [ ] **Step 4: Implement find_last_handover and collect_pr_feedback on GitHubReviewAdapter**

```python
    def find_last_handover(self, pr_number: int) -> HandoverComment | None:
        """Find the most recent handover comment on the PR."""
        pr = self._repo.get_pull(pr_number)
        best: HandoverComment | None = None
        # Check issue comments on the PR
        issue = self._repo.get_issue(pr_number)
        for comment in issue.get_comments():
            parsed = parse_handover(
                comment.body,
                str(comment.id),
                comment.created_at,
                "pr",
            )
            if parsed is not None:
                if best is None or parsed.created_at > best.created_at:
                    best = parsed
        return best

    def collect_pr_feedback(self, pr_number: int, since: datetime) -> list[FeedbackItem]:
        """Collect PR review comments and reviews posted after since."""
        pr = self._repo.get_pull(pr_number)
        items: list[FeedbackItem] = []

        # PR reviews (always included — no mention filter)
        for review in pr.get_reviews():
            if review.submitted_at and review.submitted_at <= since:
                continue
            if review.user.type == "Bot":
                continue
            if not review.body:
                continue
            items.append(FeedbackItem(
                id=str(review.id),
                author=review.user.login,
                author_type="human",
                source="pr_review",
                body=review.body,
                created_at=review.submitted_at or since,
            ))

        # PR review comments (inline — need file/line metadata)
        for comment in pr.get_review_comments():
            if comment.created_at <= since:
                continue
            if comment.user.type == "Bot":
                continue
            items.append(FeedbackItem(
                id=str(comment.id),
                author=comment.user.login,
                author_type="bot" if comment.user.type == "Bot" else "human",
                source="pr_inline",
                body=comment.body,
                file_path=comment.path,
                line_range=(comment.line or 0, comment.line or 0),
                created_at=comment.created_at,
            ))

        return items
```

- [ ] **Step 5: Run all tests**

Run: `make check`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: implement feedback collection and handover search in GitHub adapter"
```

---

### Task 8: Context Assembly

**Files:**
- Create: `src/a2sdlc/context_assembly.py`
- Test: `tests/test_context_assembly.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_context_assembly.py
"""Tests for context assembly — the uniform handover-based algorithm."""

from datetime import datetime, timezone

from a2sdlc.context_assembly import assemble_context, ContextResult
from a2sdlc.handover import FeedbackItem, HandoverComment
from a2sdlc.models import StageName


def _dt(day: int) -> datetime:
    return datetime(2026, 4, day, tzinfo=timezone.utc)


def test_first_run_no_handover():
    """First run: no handover exists, ticket body is the only context."""
    result = assemble_context(
        ticket_body="Add drag and drop support",
        issue_handover=None,
        pr_handover=None,
        issue_feedback=[],
        pr_feedback=[],
        pr_diff=None,
    )
    assert result.user_prompt == "Add drag and drop support"
    assert result.feedback == []
    assert result.current_stage is None
    assert result.is_first_run is True


def test_with_handover_and_feedback():
    """After a stage, handover body + feedback are assembled."""
    handover = HandoverComment(
        stage=StageName.IMPLEMENT,
        run_id="r1",
        body="## Implementation Complete\nAdded drag and drop.",
        created_at=_dt(10),
        location="issue",
    )
    feedback = [FeedbackItem(
        id="f1", author="jane", author_type="human",
        source="issue_comment", body="@a2sdlc drag and drop broken on mobile",
        created_at=_dt(11),
    )]
    result = assemble_context(
        ticket_body="Add drag and drop support",
        issue_handover=handover,
        pr_handover=None,
        issue_feedback=feedback,
        pr_feedback=[],
        pr_diff=None,
    )
    assert "Add drag and drop support" in result.user_prompt
    assert "Implementation Complete" in result.user_prompt
    assert "drag and drop broken on mobile" in result.user_prompt
    assert result.current_stage == StageName.IMPLEMENT
    assert result.is_first_run is False
    assert len(result.feedback) == 1


def test_pr_handover_preferred_when_later_stage():
    """If PR has a REVIEW handover and issue has IMPLEMENT, prefer REVIEW."""
    issue_ho = HandoverComment(
        stage=StageName.IMPLEMENT, run_id="r1",
        body="impl done", created_at=_dt(10), location="issue",
    )
    pr_ho = HandoverComment(
        stage=StageName.REVIEW, run_id="r2",
        body="review done", created_at=_dt(10), location="pr",  # same timestamp
    )
    result = assemble_context(
        ticket_body="ticket",
        issue_handover=issue_ho,
        pr_handover=pr_ho,
        issue_feedback=[],
        pr_feedback=[],
        pr_diff=None,
    )
    assert result.current_stage == StageName.REVIEW
    assert "review done" in result.user_prompt
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_context_assembly.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement context assembly**

```python
# src/a2sdlc/context_assembly.py
"""Uniform context assembly — finds handover, collects feedback, builds prompt."""

from __future__ import annotations

from dataclasses import dataclass, field

from a2sdlc.handover import FeedbackItem, HandoverComment, later_stage
from a2sdlc.models import StageName


@dataclass
class ContextResult:
    """Output of context assembly."""

    user_prompt: str
    feedback: list[FeedbackItem]
    current_stage: StageName | None
    is_first_run: bool


def _pick_handover(
    issue_ho: HandoverComment | None,
    pr_ho: HandoverComment | None,
) -> HandoverComment | None:
    """Pick the most recent handover, tie-breaking by pipeline stage order."""
    if issue_ho is None:
        return pr_ho
    if pr_ho is None:
        return issue_ho
    if issue_ho.created_at > pr_ho.created_at:
        return issue_ho
    if pr_ho.created_at > issue_ho.created_at:
        return pr_ho
    # Same timestamp — prefer later pipeline stage
    winner_stage = later_stage(issue_ho.stage, pr_ho.stage)
    return pr_ho if pr_ho.stage == winner_stage else issue_ho


def _format_feedback_section(items: list[FeedbackItem]) -> str:
    """Format feedback items as markdown for the agent prompt."""
    if not items:
        return ""

    lines = ["## Feedback to Address\n"]
    for item in sorted(items, key=lambda f: f.created_at):
        header = f"### {item.source} by @{item.author}"
        lines.append(header)
        if item.file_path:
            loc = f"`{item.file_path}`"
            if item.line_range:
                loc += f" lines {item.line_range[0]}-{item.line_range[1]}"
            lines.append(f"- {loc}: {item.body}")
        else:
            lines.append(item.body)
        lines.append("")
    return "\n".join(lines)


def assemble_context(
    *,
    ticket_body: str,
    issue_handover: HandoverComment | None,
    pr_handover: HandoverComment | None,
    issue_feedback: list[FeedbackItem],
    pr_feedback: list[FeedbackItem],
    pr_diff: str | None,
) -> ContextResult:
    """Uniform context assembly — one code path for all scenarios.

    1. Pick the most recent handover (issue or PR, tie-break by stage order).
    2. Combine all feedback.
    3. Build prompt: ticket body + handover body + feedback + PR diff.
    """
    handover = _pick_handover(issue_handover, pr_handover)

    all_feedback = issue_feedback + pr_feedback
    all_feedback.sort(key=lambda f: f.created_at)

    parts: list[str] = [ticket_body]

    if handover is not None:
        parts.append(handover.body)

    feedback_section = _format_feedback_section(all_feedback)
    if feedback_section:
        parts.append(feedback_section)

    if pr_diff:
        parts.append(f"## Current PR Diff\n\n{pr_diff}")

    return ContextResult(
        user_prompt="\n\n".join(parts),
        feedback=all_feedback,
        current_stage=handover.stage if handover else None,
        is_first_run=handover is None,
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_context_assembly.py -v`
Expected: PASS (all 3)

- [ ] **Step 5: Commit**

```bash
git add src/a2sdlc/context_assembly.py tests/test_context_assembly.py
git commit -m "feat: add context assembly — uniform handover-based algorithm"
```

---

### Task 9: Integrate into Dispatch — Feedback Routing + Context Assembly + Dedup

**Files:**
- Modify: `src/a2sdlc/dispatch.py`
- Test: `tests/test_dispatch.py`

This is the integration task. The dispatch function needs to:
1. Handle feedback events (resolve target stage via routing table)
2. Handle `proceed` events (resolve which gate to advance past)
3. Use context assembly for prompt building
4. Dedup: skip if handover exists newer than feedback

- [ ] **Step 1: Write failing test for feedback dispatch flow**

```python
# Append to tests/test_dispatch.py

async def test_dispatch_feedback_routes_to_implement(make_ctx):
    """Feedback event while at review stage routes to implement."""
    # Set up: last handover is from review stage, feedback comment exists
    ctx = make_ctx(
        event=PipelineEvent(key="42", trigger_stage=None, is_feedback=True),
        ticket_body="Add feature",
        # FakeWorkAdapter needs handover and feedback configured
    )
    result = await dispatch(ctx)
    # Assert IMPLEMENT stage was executed, not REVIEW
    assert result.stage == StageName.IMPLEMENT
```

The exact test setup depends on how `make_ctx` works in the existing test file. Follow the existing pattern — the key assertion is that `is_feedback=True` + last handover from REVIEW → IMPLEMENT executes.

- [ ] **Step 2: Write failing test for proceed label**

```python
async def test_dispatch_proceed_advances_past_spec_gate(make_ctx):
    """Proceed label at spec gate advances to implement."""
    # Setup: last handover from SPEC, gates.spec=human
    ctx = make_ctx(
        event=PipelineEvent(key="42", trigger_stage=None, is_feedback=False),
        # ... configure handover from spec
    )
    result = await dispatch(ctx)
    assert result.stage == StageName.IMPLEMENT
```

- [ ] **Step 3: Write failing test for dedup**

```python
async def test_dispatch_feedback_dedup_skips(make_ctx):
    """If handover is newer than all feedback, skip (already addressed)."""
    # Setup: handover at T=10, feedback at T=9
    ctx = make_ctx(
        event=PipelineEvent(key="42", trigger_stage=None, is_feedback=True),
        # handover created_at > feedback created_at
    )
    result = await dispatch(ctx)
    assert result.error == "feedback_already_addressed"
```

- [ ] **Step 4: Implement dispatch changes**

This is the largest modification. Key changes to `dispatch()`:

**a) After parsing event, resolve target stage:**

```python
    # After parse_event():
    if event.is_feedback:
        # Feedback: use context assembly + routing table
        issue_handover = ctx.work.find_last_handover(event.key)
        pr_handover = None
        if event.pr_number:
            pr_handover = ctx.review.find_last_handover(event.pr_number)

        context = assemble_context(
            ticket_body=clean_body,
            issue_handover=issue_handover,
            pr_handover=pr_handover,
            issue_feedback=ctx.work.collect_issue_feedback(
                event.key,
                issue_handover.created_at if issue_handover else datetime.min,
            ),
            pr_feedback=(
                ctx.review.collect_pr_feedback(
                    event.pr_number,
                    (pr_handover or issue_handover).created_at
                    if (pr_handover or issue_handover) else datetime.min,
                )
                if event.pr_number else []
            ),
            pr_diff=ctx.review.read_pr_diff(event.pr_number) if event.pr_number else None,
        )

        # Dedup: skip if handover is newer than all feedback
        if context.feedback and not context.is_first_run:
            handover = _pick_handover(issue_handover, pr_handover)
            newest_feedback = max(f.created_at for f in context.feedback)
            if handover and handover.created_at > newest_feedback:
                return DispatchResult(stage=StageName.SPEC, error="feedback_already_addressed")

        target_stage = resolve_target_stage(context.current_stage)
        user_prompt = context.user_prompt

    elif event.trigger_stage is None:
        # Proceed label: advance past current gate
        issue_handover = ctx.work.find_last_handover(event.key)
        current_stage = issue_handover.stage if issue_handover else None
        # Determine next stage based on current position
        if current_stage == StageName.SPEC:
            target_stage = StageName.IMPLEMENT
        elif current_stage == StageName.REVIEW:
            target_stage = StageName.MERGE
        else:
            target_stage = StageName.IMPLEMENT  # fallback
        user_prompt = clean_body

    else:
        # Normal label event
        target_stage = event.trigger_stage
        user_prompt = clean_body
```

**b) Set system prompt mode hint based on context:**

```python
    if context.is_first_run:
        prompt_hint = ""  # No hint needed — normal first-run prompt
    elif context.feedback:
        prompt_hint = "IMPORTANT: You are addressing feedback on your previous work. Focus on the feedback items below.\n\n"
    else:
        prompt_hint = ""
    system_prompt = prompt_hint + system_prompt
```

**c) Replace all `event.stage` references with `target_stage`** throughout the rest of dispatch.

**c) For feedback runs, use the assembled `user_prompt`** instead of building it ad-hoc.

**d) For REVIEW stage, still append PR context** if not already included by context assembly.

- [ ] **Step 5: Run all tests**

Run: `make check`
Expected: Fix any test failures. This will require updating existing dispatch tests that use the old `event.stage` field.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: integrate feedback routing, context assembly, and dedup into dispatch"
```

---

### Task 10: Update ProjectConfig — self_answer replaces auto_spec

**Files:**
- Modify: `src/a2sdlc/config.py`
- Modify: `src/a2sdlc/dispatch.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

```python
def test_self_answer_config():
    config = load_config_file_from_dict({"pipeline": {"spec": {"self_answer": True}}})
    assert config.self_answer is True
```

- [ ] **Step 2: Rename auto_spec to self_answer**

In `src/a2sdlc/config.py`, rename `auto_spec` to `self_answer` in `ProjectConfig`. Update `load_config_file` to read from `pipeline.spec.self_answer` instead of `pipeline.auto_spec`.

In `src/a2sdlc/dispatch.py`, rename `auto_spec` variable to `self_answer`.

- [ ] **Step 3: Run all tests, fix breakage**

Run: `make check`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: rename auto_spec to self_answer in config"
```

---

### Task 11: Clean StageResult — Remove Stage-Specific Fields

**Files:**
- Modify: `src/a2sdlc/models.py:48-57`
- Modify: `src/a2sdlc/dispatch.py` (any code reading `stage_result.pr_title` etc.)
- Modify: `src/a2sdlc/pr_lifecycle.py` (reads `stage_result` fields)
- Test: `tests/test_models.py`, `tests/test_dispatch.py`

- [ ] **Step 1: Audit all consumers of stage-specific StageResult fields**

Run: `grep -rn "pr_title\|pr_summary\|ticket_summary\|spec_path\|plan_path\|\.questions" src/a2sdlc/`

Identify every place that reads these fields. These consumers need to get the data from elsewhere (platform queries or prompt instructions).

- [ ] **Step 2: Remove stage-specific fields from StageResult**

```python
class StageResult(BaseModel):
    """Structured output from an agent stage."""

    status: StageStatus
    output: str = ""
    questions: list[str] | None = None  # Keep questions — used by SPEC stage for needs-input
```

Note: `questions` is kept because it's needed for the SPEC stage `needs-input` flow. `output` is added as the stage's freeform text. The other fields (`pr_title`, `pr_summary`, `ticket_summary`, `spec_path`, `plan_path`) are removed.

- [ ] **Step 3: Update pr_lifecycle.py**

The `update_from_result` method currently reads `stage_result.pr_title` and `stage_result.pr_summary`. Instead, the engine should read the PR's current title/body from the platform, or the stage prompt should instruct the agent to set these via its tools.

For now, remove `update_from_result` calls that depend on removed fields, or make them read from the PR directly.

- [ ] **Step 4: Update extract_result**

The `extract_result` function in `models.py` parses a JSON block from agent output. Update the expected shape to match the new `StageResult`.

- [ ] **Step 5: Run all tests, fix breakage**

Run: `make check`

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: clean StageResult — remove stage-specific fields"
```

---

### Task 12: End-to-End Smoke Test

**Files:**
- Modify: `tests/test_dispatch.py`

- [ ] **Step 1: Write integration test for full feedback cycle**

```python
async def test_full_feedback_cycle(make_ctx):
    """
    Simulate: IMPLEMENT completes → REVIEW completes → human leaves feedback
    → IMPLEMENT re-runs with feedback context.
    """
    # This test exercises the complete flow:
    # 1. Normal label-triggered IMPLEMENT run
    # 2. Normal label-triggered REVIEW run
    # 3. Feedback-triggered IMPLEMENT run (is_feedback=True)
    #    - Verify context assembly picked up the feedback
    #    - Verify feedback routing chose IMPLEMENT
    #    - Verify the runner received the feedback in its prompt
    pass  # Implement using existing make_ctx patterns
```

- [ ] **Step 2: Write integration test for proceed label at merge gate**

```python
async def test_proceed_at_merge_gate(make_ctx):
    """Proceed label when pipeline is at merge gate runs MERGE."""
    # Set up handover from REVIEW (approved), gates.merge=human
    # Apply proceed label
    # Verify MERGE stage executes
    pass
```

- [ ] **Step 3: Write integration test for dedup skip**

```python
async def test_feedback_already_addressed_skips(make_ctx):
    """If handover is newer than feedback, skip without running a stage."""
    pass
```

- [ ] **Step 4: Implement all integration tests using existing patterns**

Follow the existing test structure in `test_dispatch.py`. Use `FakeWorkAdapter` with configured handovers and feedback. Use `FakeRunner` with canned results.

- [ ] **Step 5: Run full check**

Run: `make check`
Expected: ALL tests pass

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "test: add end-to-end smoke tests for feedback cycle, proceed, and dedup"
```

---

### Task 13: Final — make check + Cleanup

- [ ] **Step 1: Run full quality gate**

Run: `make check`

Fix any remaining lint errors, type issues, or test failures.

- [ ] **Step 2: Verify handover pattern works with all stages**

```bash
python -c "from a2sdlc.handover import HANDOVER_PATTERN; print(HANDOVER_PATTERN.pattern)"
```

Expected output: `a2sdlc:(spec|implement|review|merge)`

- [ ] **Step 3: Commit any final fixes**

```bash
git add -A
git commit -m "chore: final cleanup and lint fixes"
```
