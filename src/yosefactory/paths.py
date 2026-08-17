"""Where this checkout's own directories are, found by marker rather than by counting parents.

`openspec/` and `ledger/` belong to the repository, not to any caller-supplied working directory, so
the modules that name them resolve from `__file__`. Doing that with a fixed `parents[N]` walk encodes
how deep the package happens to sit under the root: correct in a src-layout checkout, silently wrong
anywhere else, and wrong again the day a module moves between `protocol/` and `runtime/`.

Walking upward to a marker (`pyproject.toml`, `.git`) drops both assumptions. When no ancestor
carries one, the package is installed apart from its own source tree and these directories genuinely
do not exist: that raises here rather than handing back a path whose `Read` or `open` fails later,
somewhere that cannot say why.
"""

from __future__ import annotations

from pathlib import Path

_MARKERS = ("pyproject.toml", ".git")


class RepoRootNotFound(RuntimeError):
    """No ancestor carries a repository marker, so this checkout's directories cannot be named."""


def repo_root(start: Path | None = None) -> Path:
    """The nearest ancestor of `start` (this module by default) holding a marker."""
    origin = (start or Path(__file__)).resolve()
    for candidate in origin.parents:
        if any((candidate / marker).exists() for marker in _MARKERS):
            return candidate
    raise RepoRootNotFound(f"no {' or '.join(_MARKERS)} in any parent of {origin}")
