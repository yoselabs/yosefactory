"""Scrub leaked runtime state from a base branch.

When a manual ``gh pr merge`` (or UI click) closes a PR without invoking
the engine's MERGE stage, ``strip_runtime_state`` never runs and the
agent branch's ``.a2sdlc/state/state.json`` is squash-merged into base.
The branch-match guard in ``pipeline/dispatch._ensure_draft_pr`` makes
this non-fatal at runtime, but the file remains on base as a leaked
artifact. ``scrub_base`` removes it via the GitHub Contents API — no
local checkout required.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from github import UnknownObjectException

if TYPE_CHECKING:
    from github.Repository import Repository

logger = logging.getLogger(__name__)

STATE_FILE_PATH = ".a2sdlc/state/state.json"


def scrub_base(repo: Repository, base: str) -> bool:
    """Delete ``.a2sdlc/state/state.json`` from ``base`` if present.

    Returns True when a scrub commit was made, False when the file was
    already absent. Fails loudly when branch protection blocks the
    delete — caller should surface the platform's 422 to the user.
    """
    try:
        contents = repo.get_contents(STATE_FILE_PATH, ref=base)
    except UnknownObjectException:
        logger.info("scrub_base.no_op", extra={"base": base, "path": STATE_FILE_PATH})
        return False
    if isinstance(contents, list):
        # get_contents on a directory returns a list; the path is a file,
        # so this branch should be unreachable. Guard for ty narrowing.
        msg = f"{STATE_FILE_PATH} resolved to a directory on {base}"
        raise RuntimeError(msg)
    repo.delete_file(
        path=contents.path,
        message="chore(a2sdlc): scrub leaked runtime state",
        sha=contents.sha,
        branch=base,
    )
    logger.info("scrub_base.scrubbed", extra={"base": base, "sha": contents.sha})
    return True
