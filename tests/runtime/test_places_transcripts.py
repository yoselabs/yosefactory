"""K D034: transcripts get their own seam in `Places`, so a caller can point them at a durable
location outside the workspace entirely.

The defect this exists to fix: `ensure_transcripts_ignored` writes `*.stream.jsonl` into the
workspace's `.git/info/exclude` — correct for its stated purpose (S237, keeping the raw transcript
from dirtying the tree the `done` gate inspects) — but under `Places.nested` the ledger it guards
sits *inside* the workspace, so the one artefact wanted for later inspection is excluded, never
committed, and dies with the workspace's container. `Places.transcripts` gives the executor
somewhere else to write it; every existing caller, having never set it, is unaffected.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.runtime.test_turn_cycle import CREATED, FakeExecutor, git
from yosefactory.executor.outcome import RunResult
from yosefactory.protocol import backlog
from yosefactory.runtime import loop as loop_module
from yosefactory.runtime import turn
from yosefactory.runtime.config import Guardrails

TRUE_COMMAND = ("true",)


@pytest.fixture
def limits() -> Guardrails:
    return Guardrails(window=10, wall_clock_seconds=60, turn_ceiling=4, grace_seconds=1, question_deadline_hours=24, max_attempts=3)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "a2web"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.invalid")
    git(root, "config", "user.name", "T")
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(root, "add", "seed.txt")
    git(root, "commit", "-q", "-m", "seed")
    return root


def test_places_local_transcripts_defaults_to_the_ledger(tmp_path: Path) -> None:
    """`Places.local(repo)` resolves to today's location, byte for byte — unchanged."""
    repo = tmp_path / "repo"
    places = turn.Places.local(repo)

    assert places.transcripts == places.ledger


def test_places_nested_transcripts_defaults_to_the_ledger_when_omitted(tmp_path: Path) -> None:
    """Inert until a caller asks for it: `Places.nested` with no `transcripts` argument still
    writes the transcript inside the nested queue's own ledger, exactly as before this field
    existed."""
    places = turn.Places.nested(tmp_path / "ws")

    assert places.transcripts == places.ledger


def test_places_nested_transcripts_uses_the_given_path(tmp_path: Path) -> None:
    external = tmp_path / "runner" / "transcripts"
    places = turn.Places.nested(tmp_path / "ws", transcripts=external)

    assert places.transcripts == external
    assert places.transcripts != places.ledger


def test_places_for_threads_transcripts_dir_through(tmp_path: Path) -> None:
    """The CLI's `--transcripts-dir` (`_places_for`'s `transcripts` parameter) overrides whichever
    `Places` shape was resolved, local or split."""
    repo = (tmp_path / "repo").resolve()
    external = (tmp_path / "runner-transcripts").resolve()

    places = loop_module._places_for(repo, None, None, external)

    assert places.transcripts == external
    assert places.ledger == repo / turn.RUNS  # unaffected — only transcripts moved


def test_places_for_omitted_transcripts_dir_is_inert(tmp_path: Path) -> None:
    repo = (tmp_path / "repo").resolve()

    places = loop_module._places_for(repo, None, None, None)

    assert places.transcripts == places.ledger


def test_a_turn_writes_its_transcript_outside_the_workspace_when_configured(workspace: Path, limits: Guardrails) -> None:
    """The end-to-end receipt K D034 exists for: under `Places.nested` (the shape where the ledger
    sits inside the workspace), pointing `transcripts` at a directory outside the workspace lands
    the raw stream there — not inside the workspace's own tree at all, so nothing needs excluding
    and nothing dies with the workspace's container.

    Fails before this change: `Places` had no `transcripts` field, so `replace(places,
    transcripts=...)` raises `TypeError`, and no executor ever received a `transcripts_dir` keyword
    to write through.
    """
    external = workspace.parent / "runner-transcripts"
    places = replace(turn.Places.nested(workspace), transcripts=external)
    item_path = places.queue / turn.ITEMS / f"{turn.new_item_id()}.jsonl"
    turn.append(item_path, backlog.ITEM, CREATED, actor="fixture")

    class TranscriptWritingExecutor(FakeExecutor):
        """Matches what the real executor does: writes its raw transcript into `transcripts_dir`
        as a side effect of running, before `take_turn` ever reaches the `done` gate."""

        def __call__(self, frame: Mapping[str, Any], workspace: Path, limits: Guardrails, **kwargs: Any) -> RunResult:
            result = super().__call__(frame, workspace, limits, **kwargs)
            kwargs["transcripts_dir"].mkdir(parents=True, exist_ok=True)
            result.transcript_path.write_text(json.dumps({"type": "assistant"}) + "\n", encoding="utf-8")
            return result

    executor = TranscriptWritingExecutor(proposal={"event": "done", "effects": ["none"], "verified_by": "tests"})

    record = turn.take_turn(
        places, executor, limits=limits, owner="tester", skill=Path("workflows/turn-skill.md"), test_command=TRUE_COMMAND
    )

    transcript = external / f"{record.run_id}.stream.jsonl"
    assert transcript.exists()
    assert not (places.ledger / f"{record.run_id}.stream.jsonl").exists()

    # Never entered the workspace's own tree at all, so nothing was left for the gate to exclude or
    # for `git status` to report.
    assert not transcript.is_relative_to(workspace)
    assert git(workspace, "status", "--porcelain") == ""
