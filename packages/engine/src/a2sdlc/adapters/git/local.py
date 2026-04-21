"""Git adapter — local git operations via gitpython."""

from __future__ import annotations

import logging
from pathlib import Path

from git import Repo
from git.exc import GitCommandError

from a2sdlc.domain.exceptions import BlockedError

logger = logging.getLogger(__name__)


class LocalGitAdapter:
    """Git operations for the a2sdlc pipeline."""

    def __init__(self, project_root: Path) -> None:
        self._root = project_root
        self._repo = Repo(project_root)

    def setup_branch(self, branch_name: str, base: str) -> str:
        logger.info("git.setup_branch", extra={"branch": branch_name, "base": base})

        existing = [h for h in self._repo.heads if h.name == branch_name]
        if existing:
            self._repo.git.checkout(branch_name)
            # Pull latest from remote (previous stage may have pushed commits).
            try:
                self._repo.git.pull("origin", branch_name, "--no-edit")
            except GitCommandError:
                # Branch may not exist on remote yet — that's fine.
                logger.debug(
                    "git.pull_branch_not_remote", extra={"branch": branch_name}
                )
        else:
            # Try to checkout from remote if it exists there.
            try:
                self._repo.git.fetch("origin", branch_name)
                self._repo.git.checkout("-b", branch_name, f"origin/{branch_name}")
            except GitCommandError:
                # Branch doesn't exist anywhere — create fresh from current HEAD.
                self._repo.git.checkout("-b", branch_name)

        try:
            self._repo.git.fetch("origin", base)
            self._repo.git.merge(f"origin/{base}", "--no-edit")
        except GitCommandError as exc:
            try:
                self._repo.git.merge("--abort")
            except GitCommandError:
                pass
            raise BlockedError(f"merge conflict with {base}") from exc

        return branch_name

    def sync_with_base(self, base: str) -> bool:
        try:
            self._repo.git.fetch("origin", base)
            self._repo.git.merge(f"origin/{base}", "--no-edit")
            return True
        except GitCommandError:
            try:
                self._repo.git.merge("--abort")
            except GitCommandError:
                pass
            return False

    def commit_artifacts(self, message: str, paths: list[str]) -> bool:
        for path in paths:
            self._repo.git.add(path)
        if not self._repo.is_dirty():
            return False
        self._repo.git.commit("-m", message)
        return True

    def commit_empty(self, message: str) -> None:
        """Create an empty commit (used to seed a branch so GitHub will accept a PR against it)."""
        self._repo.git.commit("--allow-empty", "-m", message)

    def push(self) -> None:
        branch = self._repo.active_branch.name
        self._repo.git.push("origin", branch)

    def read_state(self) -> str | None:
        state_path = self._root / ".a2sdlc" / "state.json"
        if state_path.exists():
            return state_path.read_text()
        return None

    def write_state(self, data: str) -> None:
        state_path = self._root / ".a2sdlc" / "state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(data)
