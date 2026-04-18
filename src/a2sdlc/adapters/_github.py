"""Shared PyGithub helpers for work/github.py and review/github.py.

Leading-underscore module name signals internal to the adapters package — not
re-exported at the adapters top level. Public entry is via ``connect(repo_name, token)``
called from ``cli.py`` to build a single ``Repository`` handle, which is then passed
to both ``GitHubWorkAdapter`` and ``GitHubReviewAdapter`` constructors.
"""

from __future__ import annotations

from github import Github
from github.Repository import Repository


def connect(repo_name: str, token: str) -> Repository:
    """Create a shared PyGithub repo handle. Pass to both adapters."""
    return Github(token).get_repo(repo_name)


__all__ = ["connect"]
