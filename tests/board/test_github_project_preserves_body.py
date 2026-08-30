"""`project()` must never destroy text it did not write (the live defect: two issues carrying
hand-written specs were reduced to a marker line and a goal sentence by an ordinary projection
run, because `project()` PATCHed a freshly rendered body over whatever was already there).

Against `fake_gh.FakeGh` -- no real `gh` call, no network. See test_reprojection.py for the
real-`gh` acid test.
"""

from __future__ import annotations

from pathlib import Path

from yosefactory.board.github import MARKER, GitHubIssuesAdapter
from yosefactory.protocol import backlog
from yosefactory.protocol.eventlog import FoldedLog
from yosefactory.runtime import turn

from .fake_gh import FakeGh

REPO = "yoselabs/yosefactory-test"


def _item(tmp_path: Path, item_id: str, *, state: str = "ready") -> FoldedLog:
    path = tmp_path / f"{item_id}.jsonl"
    turn.append(
        path,
        backlog.ITEM,
        {"event": "created", "loop": "l", "frame": {"goal": "ship the thing", "method": "m", "assumptions": "a"}},
        actor="denis",
    )
    if state == "done":
        claim = {"event": "claimed", "owner": "o", "expires_at": "2099-01-01T00:00:00+00:00", "attempt": 1}
        turn.append(path, backlog.ITEM, claim, actor="o")
        turn.append(path, backlog.ITEM, {"event": "started"}, actor="o")
        turn.append(path, backlog.ITEM, {"event": "done", "effects": [], "verified_by": "test"}, actor="o")
    return backlog.load(path)


def test_a_human_authored_body_survives_projection(gh: FakeGh, tmp_path: Path) -> None:
    """The regression this change closes: a marked issue carrying real specification text below
    the marker must come out of `project()` byte-for-byte identical in that text."""
    human_spec = (
        f"<!-- {MARKER}itm-a -->\n\n"
        "## Specification\n\n"
        "This must support concurrent writers and never lose an update.\n"
        "See the design doc at docs/foo.md for the full rationale.\n"
    )
    gh.seed_issue(10, title="[ready] ship the thing", body=human_spec)
    item = _item(tmp_path, "itm-a")
    adapter = GitHubIssuesAdapter(REPO)

    adapter.project(item, "10")

    assert gh.issues[10]["body"] == human_spec  # untouched, not even re-sent
    assert gh.issues[10]["title"] == "[ready] ship the thing"


def test_projection_still_updates_the_title_on_a_state_change(gh: FakeGh, tmp_path: Path) -> None:
    human_spec = f"<!-- {MARKER}itm-b -->\n\nhand-written text that must survive\n"
    gh.seed_issue(11, title="[ready] ship the thing", body=human_spec)
    item = _item(tmp_path, "itm-b", state="done")
    adapter = GitHubIssuesAdapter(REPO)

    adapter.project(item, "11")

    assert gh.issues[11]["title"] == "[done] ship the thing"
    assert gh.issues[11]["body"] == human_spec  # title moved, body did not


def test_a_markerless_issue_gets_the_marker_prepended_not_replaced(gh: FakeGh, tmp_path: Path) -> None:
    """`ingest()`'s create path (board-projection/inbox spec): a freshly adopted, markerless
    issue can carry human text with no marker at all yet. `project()` must attach the marker
    without discarding that text -- this is the one case `project()` still writes a body at all."""
    human_text = "printer offline again -- every few hours, only on the 2nd floor"
    gh.seed_issue(12, title="printer offline again", body=human_text)
    item = _item(tmp_path, "itm-c")
    adapter = GitHubIssuesAdapter(REPO)

    adapter.project(item, "12")

    assert gh.issues[12]["body"] == f"<!-- {MARKER}itm-c -->\n\n{human_text}"


def test_a_second_projection_of_the_same_marked_issue_sends_no_body_at_all(gh: FakeGh, tmp_path: Path) -> None:
    """Once the marker is present, `project()` must not even resend the body -- a second call
    is a title-only PATCH, so there is no rendered stub to accidentally regress to."""
    calls: list[list[str]] = []
    original_api = FakeGh.api

    def _recording_api(self: FakeGh, args: list[str], *, input_text: str | None = None) -> str:
        calls.append(list(args))
        return original_api(self, args, input_text=input_text)

    gh.api = _recording_api.__get__(gh, FakeGh)  # type: ignore[method-assign]
    gh.seed_issue(13, title="[ready] ship the thing", body=f"<!-- {MARKER}itm-d -->\n\nkeep me\n")
    item = _item(tmp_path, "itm-d")
    adapter = GitHubIssuesAdapter(REPO)

    adapter.project(item, "13")

    patch_calls = [c for c in calls if "-X" in c and c[c.index("-X") + 1] == "PATCH"]
    assert len(patch_calls) == 1
    assert not any(a.startswith("body=") for a in patch_calls[0])
    assert "-F" not in patch_calls[0]
