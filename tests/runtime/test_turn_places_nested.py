"""K D033: the queue lives inside the workspace's own repository, not in one of its own.

`nest-the-queue-inside-the-workspace`'s end-to-end receipt. Before this change, `Places.nested`
did not exist and the only way to point a queue at a subdirectory of the workspace was to hand-build
`Places` with `queue_lock = queue / LOCK` — which computes a lock path under a directory that has no
`.git`, silently keying the queue lock differently from the workspace lock even though the two paths
share one tree. `test_pick_claim_work_commit_under_a_nested_queue` below is the receipt this change
promised: an item under `<workspace>/.factory/` picked, claimed, worked and committed — it fails
against the pre-change hand-built `Places` (mismatched locks/queue-not-a-repo) and passes once
`Places.nested` and `_places_for`'s nesting detection exist.

**What this file does not prove:** a real foreign workspace (an actual `a2web` checkout, a real
agent) behaves the same way — that is out of scope for this change (dispatch: no `factory-state`
migration, no wiring). It also does not prove concurrency across two nested workspaces actually
overlaps safely under load — only that two nested `Places` never share a queue path, which is the
structural property D033 relies on rather than a stress test of it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.runtime.test_turn_cycle import CREATED, FakeExecutor, git
from yosefactory.protocol import backlog
from yosefactory.protocol.turn import EnforcedBy, Outcome
from yosefactory.runtime import loop as loop_module
from yosefactory.runtime import turn
from yosefactory.runtime.config import Guardrails

SKILL = Path("workflows/turn-skill.md")
TRUE_COMMAND = ("true",)


@pytest.fixture
def limits() -> Guardrails:
    return Guardrails(window=10, wall_clock_seconds=60, turn_ceiling=4, grace_seconds=1, question_deadline_hours=24, max_attempts=3)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """One repository, playing the workspace role — its own `.factory/` subdirectory is the queue,
    not a repository of its own."""
    root = tmp_path / "a2web"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.invalid")
    git(root, "config", "user.name", "T")
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(root, "add", "seed.txt")
    git(root, "commit", "-q", "-m", "seed")
    return root


def seed_nested_item(places: turn.Places) -> Path:
    path = places.queue / turn.ITEMS / f"{turn.new_item_id()}.jsonl"
    turn.append(path, backlog.ITEM, CREATED, actor="fixture")
    return path


def test_places_nested_shape(tmp_path: Path) -> None:
    """`Places.nested` alone: the queue sits inside the workspace, and both locks collapse to the
    workspace's own — never one computed under the queue subdirectory, which has no `.git`."""
    workspace_root = tmp_path / "ws"
    places = turn.Places.nested(workspace_root)

    assert places.queue == workspace_root / ".factory"
    assert places.ledger == places.queue / turn.RUNS
    assert places.workspace == workspace_root
    assert places.queue_lock == places.workspace_lock == workspace_root / turn.LOCK


def test_places_nested_custom_subdir(tmp_path: Path) -> None:
    workspace_root = tmp_path / "ws"
    places = turn.Places.nested(workspace_root, queue_subdir=".queue")
    assert places.queue == workspace_root / ".queue"


def test_places_for_detects_nesting(tmp_path: Path) -> None:
    """The CLI's `--queue`/`--workspace` resolution must reach the same lock collapse `Places.nested`
    gives a direct caller — this is the bug the pre-change code had: `resolved_queue / LOCK` computed
    under `.factory`, a directory with no `.git` of its own."""
    workspace_root = (tmp_path / "ws").resolve()
    queue_root = workspace_root / ".factory"

    places = loop_module._places_for(workspace_root, queue_root, workspace_root)

    assert places.queue == queue_root
    assert places.queue_lock == places.workspace_lock == workspace_root / turn.LOCK


def test_places_for_still_splits_two_unrelated_repositories(tmp_path: Path) -> None:
    """The existing fully-separate shape (K D026-era: private queue, public workspace) must not
    regress — an unrelated queue keeps its own lock, distinct from the workspace's."""
    workspace_root = (tmp_path / "ws").resolve()
    queue_root = (tmp_path / "queue-repo").resolve()

    places = loop_module._places_for(workspace_root, queue_root, workspace_root)

    assert places.queue_lock == queue_root / turn.LOCK
    assert places.workspace_lock == workspace_root / turn.LOCK
    assert places.queue_lock != places.workspace_lock


def test_pick_claim_work_commit_under_a_nested_queue(workspace: Path, limits: Guardrails) -> None:
    """The end-to-end receipt: an item under `<workspace>/.factory/` is picked, claimed, worked, and
    its outcome lands committed in the workspace's own git history — one repository, one push
    target, no `factory-state` involved."""
    places = turn.Places.nested(workspace)
    item_path = seed_nested_item(places)

    executor = FakeExecutor(proposal={"event": "done", "effects": ["none"], "verified_by": "tests"}, total_cost_usd=0.42)

    record = turn.take_turn(
        places,
        executor,
        limits=limits,
        owner="tester",
        skill=SKILL,
        proposal_dir=workspace.parent,
        test_command=TRUE_COMMAND,
    )

    assert record.outcome is Outcome.ADVANCED
    assert record.enforced_by is EnforcedBy.AGENT
    assert backlog.load(item_path).state == "done"

    # The item's own commit lives in the *workspace's* git history, at the nested path — not in a
    # separate repository, and not merely written to disk (S194: a file existing is not evidence it
    # was committed).
    changed = git(workspace, "show", "--name-only", "--format=", "HEAD").splitlines()
    relative_item = str(item_path.relative_to(workspace))
    assert relative_item in changed

    # Spend follows the work (D033's Trail amendment) — the row is committed inside the *workspace*
    # repository, under the nested queue, never anywhere central.
    assert any(path.endswith("ledger/spend.jsonl") and path.startswith(".factory/") for path in changed)
    spend_log = turn.spend_log_for(places)
    assert spend_log == workspace / ".factory" / "ledger" / "spend.jsonl"
    committed_spend = git(workspace, "show", f"HEAD:{spend_log.relative_to(workspace)}")
    rows = [json.loads(line) for line in committed_spend.splitlines() if line.strip()]
    matching = [row for row in rows if row["run_id"] == record.run_id]
    assert len(matching) == 1
    assert matching[0]["total_cost_usd"] == pytest.approx(0.42)

    # Nothing left uncommitted in the shared tree.
    assert not turn._git(workspace, ["status", "--porcelain"], {}, check=False).stdout.strip()


def test_a_second_workspaces_queue_cannot_see_the_firsts_item(tmp_path: Path, limits: Guardrails) -> None:
    """D033's whole point: two workspaces never share a queue, so two concurrent turns against
    different workspaces can never pick the same item and both pay for it."""

    def make_workspace(name: str) -> Path:
        root = tmp_path / name
        root.mkdir()
        git(root, "init", "-q")
        git(root, "config", "user.email", "t@example.invalid")
        git(root, "config", "user.name", "T")
        (root / "seed.txt").write_text("seed\n", encoding="utf-8")
        git(root, "add", "seed.txt")
        git(root, "commit", "-q", "-m", "seed")
        return root

    first = turn.Places.nested(make_workspace("first"))
    second = turn.Places.nested(make_workspace("second"))
    seed_nested_item(first)

    present_in_second = turn.items(second.queue)
    assert present_in_second == []
