from __future__ import annotations

from abc import ABC, abstractmethod


class TicketAdapter(ABC):
    @abstractmethod
    def fetch(self, key: str) -> str:
        """Fetch ticket description + all comments as markdown."""

    @abstractmethod
    def get_status(self, key: str) -> str:
        """Get current ticket status (label name or Jira status)."""

    @abstractmethod
    def create_comment(self, key: str, body: str) -> str:
        """Post comment on ticket. Returns comment ID."""

    @abstractmethod
    def update_comment(self, key: str, comment_id: str, body: str) -> None:
        """Update an existing comment."""

    @abstractmethod
    def transition(self, key: str, state: str) -> None:
        """Move ticket to a new state (label or Jira transition)."""

    @abstractmethod
    def trigger_next(self, event_type: str, payload: dict) -> None:
        """Trigger next pipeline stage."""


class CodeAdapter(ABC):
    @abstractmethod
    def create_branch(self, name: str) -> None:
        """Create and checkout a new branch."""

    @abstractmethod
    def create_pr(self, title: str, body: str, head: str) -> int:
        """Create a pull request. Returns PR number."""

    @abstractmethod
    def get_pr_context(self, pr: int) -> str:
        """Get PR title, description, changed file list, and comments. NO diff."""

    @abstractmethod
    def post_review(self, pr: int, body: str, event: str) -> None:
        """Post a PR review (APPROVE, REQUEST_CHANGES, COMMENT)."""

    @abstractmethod
    def comment_on_pr(self, pr: int, body: str) -> str:
        """Post comment on PR. Returns comment ID."""

    @abstractmethod
    def update_pr_comment(self, pr: int, comment_id: str, body: str) -> None:
        """Update an existing PR comment."""

    @abstractmethod
    def merge_pr(self, pr: int) -> None:
        """Merge a PR (squash)."""
