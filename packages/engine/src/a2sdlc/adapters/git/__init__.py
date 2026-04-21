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
    def strip_runtime_state(self) -> bool:
        """Remove `.a2sdlc/state/` on the current (feature) branch + push.

        Called right before the MERGE stage merges the PR so the squash-
        merge carries a clean tree into base. The entire `.a2sdlc/state/`
        folder is treated as an opaque bag of runtime data (state.json,
        logs, handover scratch, anything we add later) and removed in one
        commit. `.a2sdlc/config.yaml` and `.a2sdlc/prompts/` are project
        config and stay.

        Writes only to the feature branch — works under branch protection,
        which typically forbids direct pushes to base.

        Returns True if a strip commit was pushed.
        """
        ...


from a2sdlc.adapters.git.local import LocalGitAdapter  # noqa: E402
from a2sdlc.adapters.git.local_branch import LocalBranchGitAdapter  # noqa: E402

__all__ = ["GitAdapter", "LocalGitAdapter", "LocalBranchGitAdapter"]
