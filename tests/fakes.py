"""Fake adapter implementations for testing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from a2sdlc.adapters.protocols import DispatchInput
from a2sdlc.config import StageConfig
from a2sdlc.exceptions import BlockedError, SkipEvent
from a2sdlc.models import StageName
from a2sdlc.runner import RunResult


# ── FakeTicketAdapter ────────────────────────────────────────────────


class FakeTicketAdapter:
    """In-memory TicketAdapter for tests. Records all calls."""

    STAGE_LABELS: dict[StageName, str] = {
        StageName.SPEC: "stage:spec",
        StageName.IMPLEMENT: "stage:implement",
        StageName.REVIEW: "stage:review",
        StageName.MERGE: "stage:merge",
    }
    TRIGGER_LABEL: str = "agent"
    BLOCKED_LABEL: str = "stage:blocked"
    DONE_LABEL: str = "stage:done"
    NEEDS_INPUT_LABEL: str = "needs-input"
    PROCEED_LABEL: str = "proceed"

    def __init__(
        self,
        event: DispatchInput | None = None,
        ticket_body: str = "",
        labels: list[str] | None = None,
        pr_for_branch: int | None = None,
    ) -> None:
        self._event = event
        self._ticket_body = ticket_body
        self._labels: list[str] = labels or []
        self._pr_for_branch = pr_for_branch

        # Call records
        self.comments: list[tuple[str, str]] = []  # (key, body)
        self.updated_comments: list[
            tuple[str, str, str]
        ] = []  # (key, comment_id, body)
        self.label_history: list[tuple[str, str]] = []  # (key, label)
        self.reviews: list[tuple[int, str, str]] = []  # (pr, body, event)
        self.merged_prs: list[tuple[int, str]] = []  # (pr, method)
        self.blocked: list[tuple[str, str]] = []  # (key, reason)
        self._comment_counter = 0

    def parse_event(self) -> DispatchInput:
        if self._event is None:
            raise SkipEvent("no event configured")
        return self._event

    def get_ticket(self, key: str) -> str:
        return self._ticket_body

    def get_labels(self, key: str) -> list[str]:
        return list(self._labels)

    def post_comment(self, key: str, body: str) -> str:
        self._comment_counter += 1
        comment_id = str(self._comment_counter)
        self.comments.append((key, body))
        return comment_id

    def update_comment(self, key: str, comment_id: str, body: str) -> None:
        self.updated_comments.append((key, comment_id, body))

    def set_stage_label(self, key: str, stage: StageName) -> None:
        label = self.STAGE_LABELS[stage]
        self.label_history.append((key, label))

    def set_done_label(self, key: str) -> None:
        self.label_history.append((key, self.DONE_LABEL))

    def set_blocked(self, key: str, reason: str) -> None:
        self.blocked.append((key, reason))
        self.label_history.append((key, self.BLOCKED_LABEL))

    def post_review(self, pr: int, body: str, event: str) -> None:
        self.reviews.append((pr, body, event))

    def get_pr_for_branch(self, branch: str) -> int | None:
        return self._pr_for_branch

    def merge_pr(self, pr: int, method: str = "squash") -> None:
        self.merged_prs.append((pr, method))


# ── FakeGitAdapter ───────────────────────────────────────────────────


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
        self.branch_setups: list[tuple[str, str]] = []  # (key, base)
        self.commits: list[tuple[str, list[str]]] = []  # (message, paths)
        self.pushes: list[None] = []
        self.written_state: list[str] = []

    def setup_branch(self, key: str, base: str) -> str:
        if self._conflict_on_setup:
            raise BlockedError("conflict on branch setup")
        self.branch_setups.append((key, base))
        return f"a2sdlc/{key}"

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


# ── FakeRunner ───────────────────────────────────────────────────────


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
    """In-memory StageRunner for tests. Returns canned result(s).

    Pass a single RunResult or a list of RunResult for sequential calls.
    """

    def __init__(self, result: RunResult | list[RunResult]) -> None:
        self._results: list[RunResult] = (
            [result] if isinstance(result, RunResult) else result
        )
        self._call_index = 0
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
        idx = min(self._call_index, len(self._results) - 1)
        self._call_index += 1
        return self._results[idx]
