"""Local-only git adapter: no origin interaction."""

from __future__ import annotations

import subprocess
from pathlib import Path

from a2sdlc.adapters.git.local import LocalGitAdapter
from a2sdlc.domain.exceptions import BlockedError


class LocalBranchGitAdapter(LocalGitAdapter):
    """GitAdapter for fully-offline use.

    Inherits state read/write (.a2sdlc/state.json), commit_artifacts from
    LocalGitAdapter. Overrides setup_branch and sync_with_base to skip any
    remote (`origin`) interaction. push() is a no-op.
    """

    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root=project_root)

    def setup_branch(self, branch_name: str, base: str) -> str:
        """Create or check out branch_name without fetching origin."""
        ls = subprocess.run(
            ["git", "rev-parse", "--verify", branch_name],
            cwd=self._root,
            capture_output=True,
            text=True,
        )
        if ls.returncode == 0:
            result = subprocess.run(
                ["git", "checkout", branch_name],
                cwd=self._root,
                capture_output=True,
                text=True,
            )
        else:
            result = subprocess.run(
                ["git", "checkout", "-b", branch_name, base],
                cwd=self._root,
                capture_output=True,
                text=True,
            )
        if result.returncode != 0:
            raise BlockedError(f"git checkout failed: {result.stderr.strip()}")
        return branch_name

    def sync_with_base(self, base: str) -> bool:
        """No-op locally — no origin to sync with."""
        return True

    def push(self) -> None:
        """No-op — local-only adapter."""
        return None
