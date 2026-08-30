"""The acid test, run for real (architecture.md §7): populate a real board from real git items,
destroy every issue, re-project, and diff snapshots read from the GitHub API -- never from this
module's own return values (S194 discipline: check the subject, not the instrument).

Requires `gh` authenticated locally with write access to `BOARD_REPO`. Marked `boardlive` --
excluded from `make check`, run explicitly: `uv run pytest -q -m boardlive tests/board/`.

Every `gh`/subprocess call below names `BOARD_REPO` explicitly and touches nothing else -- see
`orchestration.md`'s constraint on this session: no unscoped `gh` call, nothing outside the
throwaway repo.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from yosefactory.board.github import GitHubIssuesAdapter
from yosefactory.board.inbox import ingest
from yosefactory.board.projection import project_all
from yosefactory.protocol import backlog
from yosefactory.runtime import turn

BOARD_REPO = "iorlas/yosefactory-board-receipt"

FRAME_A = {"goal": "acid test item A -- ready, mid-priority", "method": "m", "assumptions": "a"}
FRAME_B = {"goal": "acid test item B -- will be marked done", "method": "m", "assumptions": "a"}

pytestmark = pytest.mark.boardlive


def _gh(*args: str, input_text: str | None = None) -> str:
    completed = subprocess.run(  # noqa: S603
        ["gh", *args], input=input_text, capture_output=True, text=True, check=False  # noqa: S607
    )
    if completed.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {completed.stderr or completed.stdout}")
    return completed.stdout


def _delete_all_issues(repo: str) -> None:
    """The board's own "destroy" step for the acid test -- not part of BoardAdapter (the spec's
    five methods have no delete; a real board is never emptied in production, only in this test).
    """
    out = _gh("api", f"repos/{repo}/issues", "--paginate", "-X", "GET", "-f", "state=all", "-f", "per_page=100")
    text = out.strip()
    issues: list[dict] = []
    decoder = json.JSONDecoder()
    pos = 0
    while pos < len(text):
        chunk, end = decoder.raw_decode(text, pos)
        issues.extend(chunk)
        pos = end
        while pos < len(text) and text[pos] in " \n\t":
            pos += 1
    for issue in issues:
        if "pull_request" in issue:
            continue
        _gh("issue", "delete", str(issue["number"]), "--repo", repo, "--yes")


def _seed_item(repo: Path, item_id: str, frame: dict, *, done: bool = False) -> None:
    (repo / turn.ITEMS).mkdir(parents=True, exist_ok=True)
    path = repo / turn.ITEMS / f"{item_id}.jsonl"
    turn.append(path, backlog.ITEM, {"event": "created", "loop": "l", "frame": frame}, actor="denis")
    if done:
        claim = {"event": "claimed", "owner": "o", "expires_at": "2099-01-01T00:00:00+00:00", "attempt": 1}
        turn.append(path, backlog.ITEM, claim, actor="o")
        turn.append(path, backlog.ITEM, {"event": "started"}, actor="o")
        turn.append(path, backlog.ITEM, {"event": "done", "effects": [], "verified_by": "acid-test"}, actor="o")


def _snapshot(adapter: GitHubIssuesAdapter) -> set[tuple[str, str, str]]:
    """(item_id, title, open/closed) triples, read straight from the GitHub API."""
    triples = set()
    for issue in adapter._issues():
        item_id = None
        for line in (issue.get("body") or "").splitlines():
            if "yosefactory:item=" in line:
                item_id = line.split("yosefactory:item=", 1)[1].split("-->", 1)[0].strip()
        if item_id is None:
            continue
        triples.add((item_id, issue["title"], issue["state"]))
    return triples


def _snapshot_stable(adapter: GitHubIssuesAdapter, expected: int, *, attempts: int = 10, delay: float = 2.0) -> set:
    """The list-issues endpoint lagged single-issue reads by more than any fixed sleep covered
    reliably during this change's own testing -- polled rather than slept-once so the receipt
    doesn't depend on guessing the right constant."""
    snapshot: set = set()
    for _ in range(attempts):
        snapshot = _snapshot(adapter)
        if len(snapshot) >= expected:
            return snapshot
        time.sleep(delay)
    return snapshot


def _git(target: Path, *args: str) -> str:
    binary = shutil.which("git")
    assert binary is not None
    completed = subprocess.run([binary, *args], cwd=target, capture_output=True, text=True, check=True)  # noqa: S603
    return completed.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real git repo -- `ingest()` (exercised by the rejected-command test below) commits what
    it applies or rejects via `runtime.turn.commit()`, which runs `git add`/`git commit` inside
    this path. A bare directory made that call fail with `fatal: not a git repository` (S243) --
    fixed here to match `test_inbox.py`'s identical fixture, the file this module's `repo` fell
    out of sync with when `ingest()` grew its commit behavior."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "T")
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(root, "add", "seed.txt")
    _git(root, "commit", "-q", "-m", "seed")
    return root


def test_reprojection_acid_test(repo: Path) -> None:
    """Polled reads follow every board mutation: GitHub's issue-**list** endpoint lagged behind
    a single-issue GET by more than a fixed sleep covered reliably (observed directly during this
    change -- a freshly created/closed issue was readable by number immediately, but absent from
    `GET .../issues?state=all` for several seconds after). That is a real property of the API this
    adapter drives, not a flaw in the projection or the test's own logic -- `_snapshot_stable`
    polls rather than guessing a constant, and the poll count/interval are visible in the assert
    message if this ever needs re-tuning.
    """
    adapter = GitHubIssuesAdapter(BOARD_REPO)
    _delete_all_issues(BOARD_REPO)  # start from a known-empty board, bounded to BOARD_REPO only

    _seed_item(repo, "itm-acid-a", FRAME_A)
    _seed_item(repo, "itm-acid-b", FRAME_B, done=True)

    project_all(repo, adapter)
    before = _snapshot_stable(adapter, expected=2)
    assert len(before) == 2, f"expected 2 projected issues before destruction, got {before}"

    _delete_all_issues(BOARD_REPO)
    time.sleep(3)
    assert _snapshot(adapter) == set(), "board did not actually empty -- acid test would be vacuous"

    project_all(repo, adapter)
    after = _snapshot_stable(adapter, expected=2)

    assert after == before, f"re-projection diverged from the pre-destruction snapshot:\nbefore={before}\nafter={after}"


def test_identity_matches_the_board_repos_owner(repo: Path) -> None:
    """S242's own live assertion: the account actually reading `BOARD_REPO` is the account it is
    owned by. `BOARD_REPO`'s owner segment is used rather than a second literal -- this test
    introduces no account name beyond what the module already names."""
    adapter = GitHubIssuesAdapter(BOARD_REPO)

    adapter._issues()

    assert adapter.identity == BOARD_REPO.split("/")[0]


def test_rejected_command_is_a_visible_reply_on_the_thread(repo: Path) -> None:
    """What Denis sees on his phone when a command does not land."""
    adapter = GitHubIssuesAdapter(BOARD_REPO)
    _delete_all_issues(BOARD_REPO)

    _seed_item(repo, "itm-acid-done", FRAME_B, done=True)
    refs = project_all(repo, adapter)
    ref = refs["itm-acid-done"]
    _snapshot_stable(adapter, expected=1)  # wait for the issue to be listable at all

    _gh("issue", "comment", ref, "--repo", BOARD_REPO, "--body", "/priority 9")

    results: list = []
    for _ in range(10):
        results = ingest(repo, adapter, actor="board-acid-test", allowed_actors=frozenset({BOARD_REPO.split("/")[0]}))
        if results:
            break
        time.sleep(2)

    assert results, "the posted command was not read back by list_events()"
    assert results[0].result == "rejected"

    comments = json.loads(_gh("api", f"repos/{BOARD_REPO}/issues/{ref}/comments"))
    reply_bodies = [c["body"] for c in comments]
    assert any(body.startswith("rejected:") for body in reply_bodies), reply_bodies
