"""`GitHubIssuesAdapter.propose` -- opening a pull request for review, against `fake_gh.FakeGh`.
No real `gh` call, no network.
"""

from __future__ import annotations

from pathlib import Path

from yosefactory.board.github import GitHubIssuesAdapter
from yosefactory.protocol import backlog
from yosefactory.runtime import turn

from .fake_gh import REPO, FakeGh

FRAME = {"goal": "fix the wifi dropping", "method": "m", "assumptions": "a"}


def _item(tmp_path: Path, item_id: str) -> backlog.FoldedLog:
    path = tmp_path / f"{item_id}.jsonl"
    turn.append(path, backlog.ITEM, {"event": "created", "loop": "l", "frame": FRAME}, actor="denis")
    return backlog.load(path)


def test_propose_opens_a_pull_request_that_closes_the_issue(gh: FakeGh, tmp_path: Path) -> None:
    gh.seed_issue(12, title="wifi", body="drops every few hours")
    item = _item(tmp_path, "itm-a")
    adapter = GitHubIssuesAdapter(REPO)

    ref = adapter.propose(item, "12", "factory/itm-a")

    pull = gh.pulls[int(ref)]
    assert pull["head"]["ref"] == "factory/itm-a"
    assert pull["base"]["ref"] == gh.default_branch
    assert "Closes #12" in pull["body"]


def test_propose_is_idempotent_for_the_same_branch(gh: FakeGh, tmp_path: Path) -> None:
    gh.seed_issue(13, title="wifi", body="drops")
    item = _item(tmp_path, "itm-b")
    adapter = GitHubIssuesAdapter(REPO)

    first = adapter.propose(item, "13", "factory/itm-b")
    second = adapter.propose(item, "13", "factory/itm-b")

    assert first == second
    assert len(gh.pulls) == 1


def test_propose_for_a_different_branch_opens_a_second_pull_request(gh: FakeGh, tmp_path: Path) -> None:
    gh.seed_issue(14, title="wifi", body="drops")
    item = _item(tmp_path, "itm-c")
    adapter = GitHubIssuesAdapter(REPO)

    first = adapter.propose(item, "14", "factory/itm-c")
    second = adapter.propose(item, "14", "factory/itm-c-retry")

    assert first != second
    assert len(gh.pulls) == 2
