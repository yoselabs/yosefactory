"""The Python integration surface: every function and class signature a runner outside this
repository may call directly. Frozen here so a change to one is a deliberate edit to this file --
a failing test with the diff attached -- rather than a silent break a runner discovers by crashing
after an image pull.

The forcing incident: `board.inbox.ingest()` gained a required, no-default `allowed_actors`
keyword-only parameter (deliberately -- a workspace is a public repository, and without an
allowlist a stranger's issue becomes a paid-for work item). `yoselabs/factory-state`'s
`runner/compat.py` checks the CLI flag surface (`--queue`, `--workspace`, `--transcripts-dir`, ...)
and stayed green, because the change was a Python signature, not a flag. `SURFACE` below is what
that check had nothing to compare against.

CLI flags are a different, already-covered question (`give-the-entrypoint-a-cross-repo-surface`,
ADR-0014): whether the entrypoint's flag surface still parses. This is the Python surface: the
exact functions and classes a runner imports and calls, and the exact signature each was written
against, expressed as `str(inspect.signature(...))` under this module's own `from __future__ import
annotations` (so annotations compare as the source-level names they were written with, not their
resolved types).

`check()` is what a runner calls before spending anything on a turn -- import this module, call
`check()`, and either it returns empty (the image still fits) or it names exactly what drifted.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Final

from yosefactory.board.adapter import BoardAdapter
from yosefactory.board.github import GitHubIssuesAdapter
from yosefactory.board.inbox import ingest
from yosefactory.board.projection import project_all
from yosefactory.protocol.eventlog import LogError
from yosefactory.runtime.turn import eligible, items


@dataclass(frozen=True, slots=True)
class Entry:
    qualname: str
    target: Any
    signature: str


def _entry(qualname: str, target: Any, signature: str) -> Entry:
    return Entry(qualname=qualname, target=target, signature=signature)


# `BoardAdapter` is a `Protocol`, not a callable a runner constructs -- it names the shape
# `ingest()`/`project_all()` require of whatever adapter a runner does construct, and is listed so a
# change to that shape (a fifth method added, a signature on one of the five changed) is caught the
# same way. `inspect.signature` on a `Protocol` class resolves its `__init__`, which is `object`'s
# and never changes; the check below reads `BoardAdapter`'s own declared methods instead of trying
# to signature-check the class itself. See `check()`.
SURFACE: Final[tuple[Entry, ...]] = (
    _entry(
        "yosefactory.board.inbox.ingest",
        ingest,
        "(repo: 'Path', adapter: 'BoardAdapter', *, actor: 'str', allowed_actors: 'frozenset[str]') -> 'list[IngestResult]'",
    ),
    _entry(
        "yosefactory.board.projection.project_all",
        project_all,
        "(repo: 'Path', adapter: 'BoardAdapter') -> 'dict[str, str]'",
    ),
    _entry(
        "yosefactory.runtime.turn.items",
        items,
        "(repo: 'Path') -> 'list[FoldedLog]'",
    ),
    _entry(
        "yosefactory.runtime.turn.eligible",
        eligible,
        "(item: 'FoldedLog') -> 'bool'",
    ),
    _entry(
        "yosefactory.protocol.eventlog.LogError",
        LogError,
        "(message: 'str', *, source: 'str', line: 'int | None' = None) -> 'None'",
    ),
    _entry(
        "yosefactory.board.github.GitHubIssuesAdapter",
        GitHubIssuesAdapter,
        "(repo: 'str') -> 'None'",
    ),
)

# `BoardAdapter`'s five methods, by name -- checked separately from `SURFACE` because it is a
# `Protocol`: nothing ever calls `BoardAdapter(...)` itself, so there is no `__init__` worth
# freezing, but `ingest()`/`project_all()` both take one as a parameter and a runner's own adapter
# (e.g. `GitHubIssuesAdapter`) is only interchangeable with it while these five hold.
_ADAPTER_METHODS: Final[tuple[Entry, ...]] = (
    _entry(
        "yosefactory.board.adapter.BoardAdapter.list_events",
        BoardAdapter.list_events,
        "(self, since: 'str | None') -> 'Sequence[Event]'",
    ),
    _entry(
        "yosefactory.board.adapter.BoardAdapter.open",
        BoardAdapter.open,
        "(self, item: 'FoldedLog') -> 'str'",
    ),
    _entry(
        "yosefactory.board.adapter.BoardAdapter.project",
        BoardAdapter.project,
        "(self, item: 'FoldedLog', ref: 'str') -> 'None'",
    ),
    _entry(
        "yosefactory.board.adapter.BoardAdapter.comment",
        BoardAdapter.comment,
        "(self, ref: 'str', body: 'str') -> 'None'",
    ),
    _entry(
        "yosefactory.board.adapter.BoardAdapter.close",
        BoardAdapter.close,
        "(self, ref: 'str', resolution: 'str') -> 'None'",
    ),
)


@dataclass(frozen=True, slots=True)
class Mismatch:
    qualname: str
    declared: str
    live: str


def check() -> tuple[Mismatch, ...]:
    """Every entry whose live signature no longer matches what this module declares.

    Empty means the surface still fits -- cheap enough to call before a runner spends anything on a
    turn. Never raises for a mismatch; `assert_fits()` below is the raising form.
    """
    mismatches: list[Mismatch] = []
    for entry in (*SURFACE, *_ADAPTER_METHODS):
        live = str(inspect.signature(entry.target))
        if live != entry.signature:
            mismatches.append(Mismatch(qualname=entry.qualname, declared=entry.signature, live=live))
    return tuple(mismatches)


class SurfaceDrift(RuntimeError):
    """The declared integration surface no longer matches the live one. Carries every mismatch."""


def assert_fits() -> None:
    """Raise `SurfaceDrift`, naming every mismatch, unless the live surface matches `SURFACE`."""
    mismatches = check()
    if not mismatches:
        return
    detail = "; ".join(f"{m.qualname}: declared {m.declared!r}, live {m.live!r}" for m in mismatches)
    raise SurfaceDrift(f"integration surface drifted: {detail}")
