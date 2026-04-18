"""Fake adapter implementations for protocol tests.

These test doubles implement WorkAdapter, ReviewAdapter, GitAdapter, and
StageRunner. They faithfully record all calls so integration tests can
assert on the exact sequence of adapter interactions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from a2sdlc.adapters.review import Approval, ReviewComment
from a2sdlc.adapters.work import PipelineEvent
from a2sdlc.config import StageConfig
from a2sdlc.domain.exceptions import BlockedError, SkipEvent
from a2sdlc.domain.handover import FeedbackItem, HandoverComment
from a2sdlc.domain.models import StageName
from a2sdlc.domain.run_result import RunResult
from a2sdlc.evaluation.progress import ProgressEvent, ProgressState


# ── FakeProgressAdapter ───────────────────────────────────────────────


class FakeProgressAdapter:
    """Records all progress adapter calls for assertions."""

    def __init__(self) -> None:
        self.started: list[tuple[str, str]] = []
        self.events: list[tuple[str, str]] = []
        self.ended: list[tuple[str, bool]] = []
        self.groups_open: list[str] = []
        self.groups_closed: int = 0

    def on_stage_start(self, stage: StageName, session_id: str) -> None:
        self.started.append((stage.value, session_id))

    def on_event(self, event_type: str, text: str) -> None:
        self.events.append((event_type, text))

    def on_stage_end(self, stage: StageName, success: bool) -> None:
        self.ended.append((stage.value, success))

    def on_group_open(self, title: str) -> None:
        self.groups_open.append(title)

    def on_group_close(self) -> None:
        self.groups_closed += 1


# ── RecordingSubscriber ───────────────────────────────────────────────


class RecordingSubscriber:
    """Captures every ``ProgressEvent`` for assertion in tests.

    Satisfies the ``Subscriber`` Protocol (async ``handle``).
    """

    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []

    async def handle(self, event: ProgressEvent) -> None:
        self.events.append(event)


# ── FakeWorkAdapter ───────────────────────────────────────────────────


class FakeWorkAdapter:
    """In-memory WorkAdapter for tests. Records all calls."""

    def __init__(
        self,
        event: PipelineEvent | None = None,
        ticket_body: str = "",
        labels: list[str] | None = None,
        issue_feedback: Sequence[FeedbackItem] = (),
        last_handover: HandoverComment | None = None,
    ) -> None:
        self._event = event
        self._ticket_body = ticket_body
        self._labels: list[str] = labels or []
        self._issue_feedback = issue_feedback
        self._last_handover = last_handover

        # Call records
        self.created_comments: list[str] = []  # comment IDs from begin_comment
        self.progress_updates: list[tuple[str, str]] = []  # (comment_id, body)
        self.finalized_comments: list[tuple[str, str]] = []  # (comment_id, body)
        self.label_history: list[tuple[str, str]] = []  # (key, label)
        self.blocked: list[tuple[str, str]] = []  # (key, reason)

        self._comment_counter = 0

    def parse_event(self) -> PipelineEvent:
        if self._event is None:
            raise SkipEvent("no event configured")
        return self._event

    def get_ticket(self, key: str) -> str:
        return self._ticket_body

    def get_labels(self, key: str) -> list[str]:
        return list(self._labels)

    def begin_comment(self, key: str) -> str:
        self._comment_counter += 1
        comment_id = f"comment-{self._comment_counter}"
        self.created_comments.append(comment_id)
        return comment_id

    def update_progress(self, comment_id: str, body: str) -> None:
        self.progress_updates.append((comment_id, body))

    def finalize_comment(self, comment_id: str, body: str) -> None:
        self.finalized_comments.append((comment_id, body))

    def set_stage_label(self, key: str, stage: StageName) -> None:
        self.label_history.append((key, f"stage:{stage.value}"))

    def set_done_label(self, key: str) -> None:
        self.label_history.append((key, "stage:done"))

    def set_blocked(self, key: str, reason: str) -> None:
        self.blocked.append((key, reason))

    def format_branch(self, ticket_key: str) -> str:
        return f"agent/{ticket_key}"

    def collect_issue_feedback(self, key: str, since: datetime) -> list[FeedbackItem]:
        return list(self._issue_feedback)

    def find_last_handover(self, key: str) -> HandoverComment | None:
        return self._last_handover


# ── FakeReviewAdapter ─────────────────────────────────────────────────


class FakeReviewAdapter:
    """In-memory ReviewAdapter for tests. Records all calls."""

    def __init__(
        self,
        pr_diff: str = "",
        pr_comments: list[ReviewComment] | None = None,
        approvals: list[Approval] | None = None,
        pr_feedback: Sequence[FeedbackItem] = (),
        pr_handover: HandoverComment | None = None,
    ) -> None:
        self._pr_diff = pr_diff
        self._pr_comments: list[ReviewComment] = pr_comments or []
        self._approvals: list[Approval] = approvals or []
        self._pr_feedback = pr_feedback
        self._pr_handover = pr_handover

        # Call records
        self.created_prs: list[
            tuple[str, str, str, str]
        ] = []  # (branch, base, title, ticket_key)
        self.updated_prs: list[
            tuple[int, str, str, str]
        ] = []  # (pr_number, title, body, ticket_key)
        self.ready_prs: list[int] = []  # pr_numbers
        self.merged_prs: list[tuple[int, str]] = []  # (pr_number, method)
        self.reviews: list[tuple[int, str, str]] = []  # (pr_number, body, verdict)

        self._pr_counter = 0

    def create_draft_pr(
        self,
        branch: str,
        base: str,
        title: str,
        ticket_key: str,
    ) -> int:
        self._pr_counter += 1
        self.created_prs.append((branch, base, title, ticket_key))
        return self._pr_counter

    def update_pr(self, pr_number: int, title: str, body: str, ticket_key: str) -> None:
        self.updated_prs.append((pr_number, title, body, ticket_key))

    def mark_pr_ready(self, pr_number: int) -> None:
        self.ready_prs.append(pr_number)

    def merge_pr(self, pr_number: int, method: str = "squash") -> None:
        self.merged_prs.append((pr_number, method))

    def get_approvals(self, pr_number: int) -> list[Approval]:
        return list(self._approvals)

    def post_review(self, pr_number: int, body: str, verdict: str) -> None:
        self.reviews.append((pr_number, body, verdict))

    def read_pr_diff(self, pr_number: int) -> str:
        return self._pr_diff

    def read_pr_comments(self, pr_number: int) -> list[ReviewComment]:
        return list(self._pr_comments)

    def collect_pr_feedback(
        self, pr_number: int, since: datetime
    ) -> list[FeedbackItem]:
        return list(self._pr_feedback)

    def find_last_handover(self, pr_number: int) -> HandoverComment | None:
        return self._pr_handover


# ── FakeGitAdapter ────────────────────────────────────────────────────


class FakeGitAdapter:
    """In-memory GitAdapter for tests. Records all calls."""

    def __init__(
        self,
        state_json: str | None = None,
        conflict_on_setup: bool = False,
    ) -> None:
        self._state_json = state_json
        self._conflict_on_setup = conflict_on_setup

        # Call records
        self.branch_setups: list[tuple[str, str]] = []  # (branch_name, base)
        self.commits: list[tuple[str, list[str]]] = []  # (message, paths)
        self.pushes: list[None] = []
        self.written_state: list[str] = []

    def setup_branch(self, branch_name: str, base: str) -> str:
        if self._conflict_on_setup:
            raise BlockedError("conflict on branch setup")
        self.branch_setups.append((branch_name, base))
        return branch_name

    def sync_with_base(self, base: str) -> bool:
        return True

    def commit_artifacts(self, message: str, paths: list[str]) -> bool:
        self.commits.append((message, paths))
        return True

    def push(self) -> None:
        self.pushes.append(None)

    def read_state(self) -> str | None:
        return self._state_json

    def write_state(self, data: str) -> None:
        self.written_state.append(data)
        self._state_json = data


# ── FakeRunner ────────────────────────────────────────────────────────


@dataclass
class RunnerCall:
    """Record of a single StageRunner.run() invocation."""

    user_prompt: str
    system_prompt: str
    config: StageConfig
    ticket_key: str
    stage: StageName
    project_root: str
    progress_state: ProgressState
    is_resume: bool
    branch: str


class FakeRunner:
    """In-memory StageRunner for tests. Returns canned result(s).

    Pass a single RunResult or a list of RunResult for sequential calls.
    """

    def __init__(self, result: RunResult | list[RunResult]) -> None:
        self._results: list[RunResult] = (
            [result] if isinstance(result, RunResult) else result
        )
        self._call_index = 0
        self.calls: list[RunnerCall] = []

    async def run(  # noqa: PLR0913
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
        self.calls.append(
            RunnerCall(
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
        )
        idx = min(self._call_index, len(self._results) - 1)
        self._call_index += 1
        return self._results[idx]


class FakeStageRunner:
    """Default fake runner for CLI smoke tests.

    Returns a successful ``RunResult`` whose ``output`` contains a valid
    ``a2sdlc`` status block so the dispatch success path runs end-to-end.
    """

    def __init__(
        self,
        status: str = "complete",
        body: str = "Fake stage handover.",
    ) -> None:
        self._status = status
        self._body = body
        self.calls: list[RunnerCall] = []

    async def run(  # noqa: PLR0913
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
        self.calls.append(
            RunnerCall(
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
        )
        output = (
            f"{self._body}\n\n"
            "```a2sdlc\n"
            f'{{"status": "{self._status}", "output": "{self._body}"}}\n'
            "```\n"
        )
        return RunResult(
            success=True,
            output=output,
            error=None,
            session_id="fake-session",
            total_cost_usd=0.0,
            duration_ms=1,
            input_tokens=1,
            output_tokens=1,
            num_turns=1,
            tool_log=[],
            progress=None,
        )
