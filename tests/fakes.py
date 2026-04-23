"""Fake adapter implementations for protocol tests.

These test doubles implement WorkAdapter, ReviewAdapter, GitAdapter, and
StageRunner. They faithfully record all calls so integration tests can
assert on the exact sequence of adapter interactions.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from a2sdlc.adapters.review import Approval, ReviewComment
from a2sdlc.config import ProjectConfig, StageConfig
from a2sdlc.domain.exceptions import BlockedError, SkipEvent
from a2sdlc.domain.handover import FeedbackItem, HandoverComment
from a2sdlc.domain.models import StageName
from a2sdlc.domain.pipeline_event import PipelineEvent
from a2sdlc.domain.progress import ProgressEvent, ProgressState
from a2sdlc.domain.run_context import RunContext
from a2sdlc.domain.run_intent import RunIntent
from a2sdlc.domain.run_result import DispatchResult, RunResult
from a2sdlc.domain.stage_outcome import InlineComment
from a2sdlc import ingress
from a2sdlc.pipeline import gating


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
        ticket_title: str = "Test ticket",
        labels: list[str] | None = None,
        issue_feedback: Sequence[FeedbackItem] = (),
        last_handover: HandoverComment | None = None,
        is_active: bool = True,
    ) -> None:
        self._event = event
        self._ticket_body = ticket_body
        self._ticket_title = ticket_title
        self._labels: list[str] = labels or []
        self._issue_feedback = issue_feedback
        self._last_handover = last_handover
        self._is_active = is_active

        # Call records
        self.created_comments: list[str] = []  # comment IDs from begin_comment
        self.progress_updates: list[tuple[str, str]] = []  # (comment_id, body)
        self.finalized_comments: list[tuple[str, str]] = []  # (comment_id, body)
        self.label_history: list[tuple[str, str]] = []  # (key, label)
        self.blocked: list[tuple[str, str]] = []  # (key, reason)
        self.needs_input: list[str] = []

        self._comment_counter = 0

    def parse_event(self) -> PipelineEvent:
        if self._event is None:
            raise SkipEvent("no event configured")
        return self._event

    def is_ticket_active(self, key: str) -> bool:
        return self._is_active

    def get_ticket(self, key: str) -> str:
        return self._ticket_body

    def get_ticket_title(self, key: str) -> str:
        return self._ticket_title

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

    def get_current_stage(self, key: str) -> StageName | None:
        # Return the last set stage from label_history if any.
        for k, label in reversed(self.label_history):
            if k == key and label.startswith("stage:"):
                name = label.removeprefix("stage:")
                try:
                    return StageName(name)
                except ValueError:
                    return None
        return None

    def set_current_stage(self, key: str, stage: StageName) -> None:
        self.label_history.append((key, f"stage:{stage.value}"))

    def mark_done(self, key: str) -> None:
        self.label_history.append((key, "stage:done"))

    def mark_blocked(self, key: str, reason: str) -> None:
        self.blocked.append((key, reason))

    def mark_needs_input(self, key: str) -> None:
        self.needs_input.append(key)

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
        self.updated_titles: list[tuple[int, str]] = []  # (pr_number, title)
        self.ready_prs: list[int] = []  # pr_numbers
        self.merged_prs: list[tuple[int, str]] = []  # (pr_number, method)
        self.reviews: list[tuple[int, str, str]] = []  # (pr_number, body, verdict)
        self.inline_comments: list[
            tuple[int, list[InlineComment]]
        ] = []  # (pr_number, comments)

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

    def update_pr_title(self, pr_number: int, title: str) -> None:
        self.updated_titles.append((pr_number, title))

    def mark_pr_ready(self, pr_number: int) -> None:
        self.ready_prs.append(pr_number)

    def merge_pr(self, pr_number: int, method: str = "squash") -> None:
        self.merged_prs.append((pr_number, method))

    def get_approvals(self, pr_number: int) -> list[Approval]:
        return list(self._approvals)

    def post_review(self, pr_number: int, body: str, verdict: str) -> None:
        self.reviews.append((pr_number, body, verdict))

    def post_inline_comments(
        self, pr_number: int, comments: list[InlineComment]
    ) -> None:
        self.inline_comments.append((pr_number, list(comments)))

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
        self.empty_commits: list[str] = []  # messages from commit_empty
        self.pushes: list[None] = []
        self.written_state: list[str] = []
        self.state_strips: int = 0

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

    def commit_empty(self, message: str) -> None:
        self.empty_commits.append(message)

    def push(self) -> None:
        self.pushes.append(None)

    def read_state(self) -> str | None:
        return self._state_json

    def write_state(self, data: str) -> None:
        self.written_state.append(data)
        self._state_json = data

    def strip_runtime_state(self) -> bool:
        self.state_strips += 1
        return True


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


# ── RunContext factory ───────────────────────────────────────────


_DEFAULT_COMPLETE_OUTPUT = '```a2sdlc\n{"status": "complete", "output": "Done"}\n```'


def default_run_result(output: str = _DEFAULT_COMPLETE_OUTPUT) -> RunResult:
    """Canonical RunResult used in dispatch tests."""
    return RunResult(
        success=True,
        output=output,
        total_cost_usd=0.5,
        input_tokens=1000,
        output_tokens=2000,
        duration_ms=5000,
        num_turns=10,
    )


def make_dispatch_context(
    *,
    event: PipelineEvent | None = None,
    ticket_body: str = "Build patient form",
    labels: list[str] | None = None,
    last_handover: HandoverComment | None = None,
    issue_feedback: Sequence[FeedbackItem] = (),
    state_json: str | None = None,
    runner_results: list[RunResult] | None = None,
    run_id: str | None = "run-1",
    project_root: Path | None = None,
    config: ProjectConfig | None = None,
) -> tuple[RunContext, FakeWorkAdapter, FakeGitAdapter, FakeReviewAdapter, FakeRunner]:
    """Build a RunContext with fakes for all adapters.

    Returns the context plus each fake so tests can assert on recorded calls.
    """
    event = event or PipelineEvent(key="35", trigger_stage=StageName.SPEC)
    work = FakeWorkAdapter(
        event=event,
        ticket_body=ticket_body,
        labels=labels,
        last_handover=last_handover,
        issue_feedback=issue_feedback,
    )
    git = FakeGitAdapter(state_json=state_json)
    review = FakeReviewAdapter()
    runner = FakeRunner(runner_results or [default_run_result()])
    project_root = project_root or Path("/tmp/test")
    ctx = RunContext(
        work=work,
        git=git,
        review=review,
        runner=runner,
        progress_state=ProgressState(project_root=str(project_root)),
        config=config or ProjectConfig(),
        project_root=project_root,
        logger=logging.getLogger("test"),
        run_id=run_id,
    )
    return ctx, work, git, review, runner


def populate_run_intent(ctx: RunContext) -> RunIntent:
    """Replacement for the legacy ``run_preflight(ctx)`` test helper.

    Runs ingress directly — ``parse_event`` → closed / ticket-active
    short-circuits → ``resolve_intent``. Kept here rather than in a
    production path because only standalone-stage tests need the shape:
    ``dispatch()`` calls the same primitives at the composition root.
    """
    parsed = ingress.parse_event(ctx)
    if isinstance(parsed, ingress.ParsedSkip):
        msg = f"parse_event short-circuited: {parsed.reason}"
        raise AssertionError(msg)
    event = parsed
    if event.is_closed:
        raise AssertionError("parse_event returned closed ticket")
    if reason := gating.check(ctx, event):
        msg = f"gating blocked: {reason}"
        raise AssertionError(msg)
    intent = ingress.resolve_intent(ctx, event)
    if isinstance(intent, DispatchResult):
        msg = f"resolve_intent short-circuited: {intent!r}"
        raise AssertionError(msg)
    return intent
