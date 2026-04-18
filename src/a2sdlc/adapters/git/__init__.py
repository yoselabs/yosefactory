"""GitAdapter Protocol + in-tree git impls."""

from __future__ import annotations

from typing import Protocol


class GitAdapter(Protocol):
    """Local git operations."""

    def setup_branch(self, branch_name: str, base: str) -> str: ...
    def sync_with_base(self, base: str) -> bool: ...
    def commit_artifacts(self, message: str, paths: list[str]) -> bool: ...
    def push(self) -> None: ...
    def read_state(self) -> str | None: ...
    def write_state(self, data: str) -> None: ...


from a2sdlc.adapters.git.local import LocalGitAdapter  # noqa: E402
from a2sdlc.adapters.git.local_branch import LocalBranchGitAdapter  # noqa: E402

__all__ = ["GitAdapter", "LocalGitAdapter", "LocalBranchGitAdapter"]
