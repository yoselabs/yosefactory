"""An in-memory `gh api` transport for `GitHubIssuesAdapter` unit tests -- no real `gh` call, no
network. See `test_reprojection.py` for the real-`gh` acid test (marked `boardlive`, excluded from
`make check`); these tests prove the same adapter code a different way, deterministically and for
free.

Only `_api` -- the one method that shells out -- is replaced. `_issues()`, `_paginated_json_array`,
`list_events()`, `open()`, `project()` and `_render()` all run as shipped.

Shared by `test_github_create.py` and `test_github_project_preserves_body.py`; pulled out of the
former when the latter needed the same fake plus one more call shape (a bare single-issue GET,
`project()`'s new preflight read).
"""

from __future__ import annotations

import json

import pytest

from yosefactory.board.github import GitHubIssuesAdapter

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
        if path.startswith(f"repos/{REPO}/issues/") and "-X" not in args:
            number = int(path.rsplit("/", 1)[-1])
            return json.dumps(self.issues[number])
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
