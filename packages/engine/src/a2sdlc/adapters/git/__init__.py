"""GitAdapter Protocol + in-tree git impls."""

from __future__ import annotations

from typing import Protocol


class GitAdapter(Protocol):
    """Local git operations."""

    def setup_branch(self, branch_name: str, base: str) -> str: ...
    def sync_with_base(self, base: str) -> bool: ...
    def commit_artifacts(self, message: str, paths: list[str]) -> bool: ...
    def commit_empty(self, message: str) -> None: ...
    def push(self) -> None: ...
    def read_state(self) -> str | None: ...
    def write_state(self, data: str) -> None: ...
    def strip_runtime(self) -> bool:
        """Remove transient per-ticket runtime files from the current branch.

        Deletes `.a2sdlc/state.json`, `.a2sdlc/logs/`, `.a2sdlc/handover/` and
        commits the deletion. Called before the final squash-merge so runtime
        noise never reaches the base branch (and thus never leaks into the
        next ticket checked out from base). `.a2sdlc/config.yaml` and
        `.a2sdlc/prompts/` are project config and stay.

        Returns True if a deletion commit was produced.
        """
        ...


from a2sdlc.adapters.git.local import LocalGitAdapter  # noqa: E402
from a2sdlc.adapters.git.local_branch import LocalBranchGitAdapter  # noqa: E402

__all__ = ["GitAdapter", "LocalGitAdapter", "LocalBranchGitAdapter"]
