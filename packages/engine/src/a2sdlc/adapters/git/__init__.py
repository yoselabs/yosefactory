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
    def cleanup_base(self, base: str) -> bool:
        """Remove per-ticket runtime files from the base branch and push.

        Deletes `.a2sdlc/state.json`, `.a2sdlc/logs/`, `.a2sdlc/handover/`
        from the base branch's tip. Called AFTER a successful squash-merge
        so leaked runtime artifacts never accumulate on base (and thus
        never leak into the next ticket checked out from base).
        `.a2sdlc/config.yaml` and `.a2sdlc/prompts/` are project config and
        stay.

        Running this post-merge (rather than pre-merge) keeps branch state
        intact if `pr_lifecycle.merge` fails so the stage can be retried.

        Returns True if a cleanup commit was pushed.
        """
        ...


from a2sdlc.adapters.git.local import LocalGitAdapter  # noqa: E402
from a2sdlc.adapters.git.local_branch import LocalBranchGitAdapter  # noqa: E402

__all__ = ["GitAdapter", "LocalGitAdapter", "LocalBranchGitAdapter"]
