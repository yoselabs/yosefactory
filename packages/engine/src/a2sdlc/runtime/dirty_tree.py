"""Dirty-tree + protected-base guards. Spec CLI surface steps 3-4."""

from __future__ import annotations

import subprocess
from pathlib import Path


class DirtyTreeError(RuntimeError):
    pass


class BaseProtectedError(RuntimeError):
    pass


def ensure_clean_tree(repo: Path) -> None:
    out = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    bad: list[str] = []
    for line in out:
        # `git status --porcelain` format: "XY path"; for untracked it's "?? path".
        if not line:
            continue
        code = line[:2]
        path = line[3:]
        if code == "??":
            if path.strip().startswith(".a2sdlc/"):
                bad.append(line)
        else:
            bad.append(line)
    if bad:
        raise DirtyTreeError(
            "working tree has uncommitted changes:\n"
            + "\n".join(bad)
            + "\ncommit, stash, or reset before running."
        )


def ensure_base_not_protected(base: str, *, protected: set[str], allow: bool) -> None:
    if allow:
        return
    if base in protected:
        raise BaseProtectedError(
            f"refusing to run on protected base {base!r}. "
            "pass --allow-protected-base to override."
        )
