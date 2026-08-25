"""S242: `GitHubIssuesAdapter` resolves and records which `gh` identity answered a board read.

Unlike `test_github_create.py`, this module patches `subprocess.run` rather than `_api` --
the enrichment this fix adds (`who = f" as {self.identity!r}"`) lives inside `_api` itself, so a
test replacing `_api` wholesale would never exercise it. No real `gh` call, no network.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field

import pytest

from yosefactory.board.github import BoardError, GitHubIssuesAdapter

REPO = "yoselabs/yosefactory-test"


@dataclass
class _Completed:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass
class _FakeSubprocess:
    """Two responses only: whatever `gh api user` should answer, and whatever the one other
    call in a given test should answer -- these tests never need more than one real read."""

    user: _Completed
    other: _Completed
    argvs: list[list[str]] = field(default_factory=list)

    def run(self, argv: list[str], **_: object) -> _Completed:
        self.argvs.append(argv)
        return self.user if argv[-1] == "user" else self.other


def test_identity_resolves_once_and_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeSubprocess(
        user=_Completed(0, stdout=json.dumps({"login": "denis"})),
        other=_Completed(0, stdout="[]"),
    )
    monkeypatch.setattr(subprocess, "run", fake.run)
    adapter = GitHubIssuesAdapter(REPO)

    assert adapter.identity is None  # nothing read yet
    adapter.list_events(since=None)
    adapter.list_events(since=None)  # a second read must not re-resolve

    assert adapter.identity == "denis"
    assert sum(1 for argv in fake.argvs if argv[-1] == "user") == 1


def test_a_failed_call_names_the_resolved_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeSubprocess(
        user=_Completed(0, stdout=json.dumps({"login": "denis"})),
        other=_Completed(1, stdout="", stderr="HTTP 404: Not Found"),
    )
    monkeypatch.setattr(subprocess, "run", fake.run)
    adapter = GitHubIssuesAdapter(REPO)

    with pytest.raises(BoardError, match="as 'denis'"):
        adapter.list_events(since=None)


def test_identity_resolution_failing_does_not_block_the_read(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeSubprocess(
        user=_Completed(1, stdout="", stderr="gh: not logged in"),
        other=_Completed(0, stdout="[]"),
    )
    monkeypatch.setattr(subprocess, "run", fake.run)
    adapter = GitHubIssuesAdapter(REPO)

    events = adapter.list_events(since=None)  # the read itself still succeeds

    assert events == []
    assert adapter.identity is None


def test_a_failed_call_with_no_identity_names_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """The `_api` message degrades cleanly -- no ` as None` or similar noise -- when identity
    could not be resolved at all."""
    fake = _FakeSubprocess(
        user=_Completed(1, stdout="", stderr="gh: not logged in"),
        other=_Completed(1, stdout="", stderr="HTTP 404: Not Found"),
    )
    monkeypatch.setattr(subprocess, "run", fake.run)
    adapter = GitHubIssuesAdapter(REPO)

    with pytest.raises(BoardError) as excinfo:
        adapter.list_events(since=None)

    assert " as " not in str(excinfo.value)
