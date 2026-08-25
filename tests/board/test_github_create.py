"""GitHubIssuesAdapter's markerless-issue intake path, against a fake `gh` transport this test
owns -- no real `gh` call, no network. See test_reprojection.py for the real-`gh` acid test
(marked `boardlive`, excluded from `make check`, requires an authenticated `gh` against a real
repo); this module proves the same adapter code a different way, deterministically and for free.

Only `_api` -- the one method that shells out -- is replaced. `_issues()`, `_paginated_json_array`,
`list_events()`, `project()` and `_render()` all run as shipped.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yosefactory.board.github import MARKER, GitHubIssuesAdapter
from yosefactory.protocol import backlog
from yosefactory.runtime import turn

REPO = "yoselabs/yosefactory-test"


class FakeGh:
    """An in-memory GitHub issues store, keyed the same way the real API responds."""

    def __init__(self, *, login: str = "denis") -> None:
        self.issues: dict[int, dict] = {}
        self.comments: dict[int, list[dict]] = {}
        self.login = login

    def seed_issue(self, number: int, *, title: str, body: str, created_at: str = "2026-08-24T00:00:00Z") -> None:
        self.issues[number] = {
            "number": number,
            "title": title,
            "body": body,
            "state": "open",
            "user": {"login": "denis"},
            "created_at": created_at,
        }
        self.comments[number] = []

    def api(self, args: list[str], *, input_text: str | None = None) -> str:
        path = args[0]
        if path == "user":
            return json.dumps({"login": self.login})
        if path == f"repos/{REPO}/issues" and "--paginate" in args:
            return json.dumps(list(self.issues.values()))
        if path.startswith(f"repos/{REPO}/issues/") and path.endswith("/comments") and "--paginate" in args:
            number = int(path.split("/")[-2])
            return json.dumps(self.comments.get(number, []))
        if path.startswith(f"repos/{REPO}/issues/") and "-X" in args and args[args.index("-X") + 1] == "PATCH":
            number = int(path.rsplit("/", 1)[-1])
            fields = {a.split("=", 1)[0]: a.split("=", 1)[1] for a in args if a.startswith("title=")}
            if "title" in fields:
                self.issues[number]["title"] = fields["title"]
            if input_text is not None:
                self.issues[number]["body"] = input_text
            return json.dumps(self.issues[number])
        raise AssertionError(f"FakeGh does not model this call: {args}")


@pytest.fixture
def gh(monkeypatch: pytest.MonkeyPatch) -> FakeGh:
    fake = FakeGh()

    def _api(self: GitHubIssuesAdapter, args: list[str], *, input_text: str | None = None) -> str:
        assert self.repo == REPO
        return fake.api(args, input_text=input_text)

    monkeypatch.setattr(GitHubIssuesAdapter, "_api", _api)
    return fake


def test_a_markerless_issue_yields_a_create_event(gh: FakeGh) -> None:
    gh.seed_issue(7, title="wifi keeps dropping", body="every few hours")
    adapter = GitHubIssuesAdapter(REPO)

    events = adapter.list_events(since=None)

    assert [e.type for e in events] == ["create"]
    assert events[0].payload["ref"] == "7"
    assert events[0].payload["title"] == "wifi keeps dropping"
    assert events[0].payload["body"] == "every few hours"


def test_an_issue_with_a_marker_is_never_a_create_candidate(gh: FakeGh) -> None:
    gh.seed_issue(8, title="[ready] existing item", body=f"<!-- {MARKER}itm-existing -->\nsomething")
    adapter = GitHubIssuesAdapter(REPO)

    events = adapter.list_events(since=None)

    assert events == []  # no comments posted either -- nothing to report


def test_projecting_the_new_item_back_removes_it_as_a_create_candidate(gh: FakeGh, tmp_path: Path) -> None:
    """The structural double-ingest guard: the same fake `gh` state, read twice, before and
    after the marker write-back `ingest()`'s create branch performs."""
    gh.seed_issue(9, title="printer offline again", body="")
    adapter = GitHubIssuesAdapter(REPO)

    before = adapter.list_events(since=None)
    assert [e.type for e in before] == ["create"]

    item_path = tmp_path / "itm-fake.jsonl"
    turn.append(
        item_path,
        backlog.ITEM,
        {"event": "created", "loop": "board-intake", "frame": {"goal": "g", "method": "m", "assumptions": "a"}},
        actor="board",
    )
    item = backlog.load(item_path)
    adapter.project(item, "9")  # ingest()'s own call, exactly as board/inbox.py makes it

    after = adapter.list_events(since=None)
    assert after == []  # the marker landed on issue 9's body -- it is no longer a candidate
