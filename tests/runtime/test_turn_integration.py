"""The integration receipt `add-take-turn-integration-receipt` recorded as owed.

Every receipt in `tests/executor/test_integration.py` drives `executor.claude.run()` directly. None
of them drives `runtime.turn.take_turn` — the reducer that claims, runs, disposes, commits and
publishes — against a real executor. This file is that receipt: one real `claude` binary, a real
second (foreign) workspace repository, a trivial one-line-file task.

Skipped when `claude` is absent or the pinned version has moved, exactly like the executor receipts.

**What this file does not prove, so a later reader does not credit it with more than it demonstrates:**

- **The `done` path was unreachable, and now is not (`teach-event-vocabulary`).** A real run during
  development of this file showed the agent does the actual work correctly -- a real commit lands in
  the workspace -- and then cannot legally report it: `workflows/turn-skill.md` never taught the event
  vocabulary (`done` needs `effects` and `verified_by`; nothing reachable by an unattended agent named
  that), so the agent invented an event name and `take_turn` correctly refused it. That gap is closed:
  `Invocation.vocabulary` now points the agent at `backlog-item-format/spec.md`'s own table
  (`teach-event-vocabulary/proposal.md`), and
  `test_a_real_agent_reaches_done_once_the_vocabulary_is_reachable` below is the receipt, asserting
  from the run's own transcript that the agent actually read the pointer rather than guessing right.
  The two tests above it still expect `Outcome.FAILED` -- **for a different, still-real reason now**:
  they call `take_turn` with no `test_command` override, so `verify.may_write_done` runs the default
  `pytest -q` inside a throwaway workspace that has no test suite, and the gate correctly refuses a
  `done` it cannot verify. That refusal is `take_turn` working correctly, and it is why those two
  tests are kept rather than deleted: an agent that reaches a legal `done` proposal but fails
  independent verification is still a real, reachable outcome worth a receipt.
- The executor wrapper below runs under `IsolationPolicy(isolated=False, workspace_scoped=True, ...)`,
  never `isolated=True` -- a throwaway probe against this same binary showed `isolated=True` denies
  every tool call headlessly (`permission_denials` on the terminal event, the target file absent from
  disk afterward; see the proposal's Finding). A task requiring a tool call cannot run under the
  default posture at all, so this file does not exercise it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from yosefactory.executor import claude
from yosefactory.executor.claude import PINNED_VERSION, resolve_version
from yosefactory.executor.invocation import Invocation
from yosefactory.executor.outcome import RunResult
from yosefactory.protocol import backlog
from yosefactory.protocol.turn import Outcome
from yosefactory.runtime import turn
from yosefactory.runtime.config import Guardrails
from yosefactory.runtime.isolation import IsolationPolicy
from yosefactory.runtime.runs import read_window

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        shutil.which("claude") is None or resolve_version() != PINNED_VERSION,
        reason=f"needs claude {PINNED_VERSION} on PATH",
    ),
]

SKILL = Path("workflows/turn-skill.md").resolve()

LIMITS = Guardrails(
    window=10,
    wall_clock_seconds=180,
    turn_ceiling=8,
    grace_seconds=10,
    question_deadline_hours=24,
    max_attempts=3,
    cost_ceiling_usd=1.0,
)

# The only posture under which an unattended tool-using turn can act at all (see module docstring).
_POLICY = IsolationPolicy(
    isolated=False,
    workspace_scoped=True,
    allowed_tools=("Bash", "Write", "Edit", "Read"),
    opt_out_reason="foreign workspace needs real tool use; isolated=True denies every tool call headlessly",
)


def real_executor(
    frame: Mapping[str, Any],
    workspace: Path,
    limits: Guardrails,
    *,
    run_id: str,
    runs_dir: Path,
    transcripts_dir: Path,
    context: Mapping[str, Any] | None = None,
    invocation: Invocation | None = None,
) -> RunResult:
    """Matches `turn.Executor` exactly. No `recorder` -- `take_turn` already owns the ledger row."""
    return claude.run(
        frame,
        workspace,
        limits,
        run_id=run_id,
        runs_dir=runs_dir,
        transcripts_dir=transcripts_dir,
        context=context,
        invocation=invocation,
        policy=_POLICY,
    )


def git(repo: Path, *args: str) -> str:
    binary = shutil.which("git")
    assert binary is not None
    completed = subprocess.run([binary, *args], cwd=repo, capture_output=True, text=True, check=True)  # noqa: S603
    return completed.stdout.strip()


def _init_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.invalid")
    git(root, "config", "user.name", "T")
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(root, "add", "seed.txt")
    git(root, "commit", "-q", "-m", "seed")
    return root


@pytest.fixture
def queue(tmp_path: Path) -> Path:
    root = _init_repo(tmp_path / "queue")
    (root / turn.ITEMS).mkdir(parents=True)
    (root / turn.QUESTIONS).mkdir(parents=True)
    return root


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A second repository, with no queue directories of its own -- the agent's foreign target."""
    return _init_repo(tmp_path / "workspace")


def places(queue: Path, workspace: Path) -> turn.Places:
    return turn.Places(
        queue=queue,
        ledger=queue / turn.RUNS,
        queue_lock=queue / turn.LOCK,
        workspace=workspace,
        workspace_lock=workspace / turn.LOCK,
        transcripts=queue / turn.RUNS,
    )


def frame_for(marker: str) -> dict[str, str]:
    """Goal and method for the work only -- D019's frame, never a channel for operating instructions.

    The "write one JSON event to `proposal_path`" instruction travels through `Invocation`/the skill,
    exactly as every other turn's does; it does not belong here.
    """
    return {
        "goal": f"notes.txt in this repository ends with the line '{marker}', committed to git.",
        "method": "Append the line to notes.txt (creating it if absent), then `git add` and `git commit` the change.",
        "assumptions": "git user.name and user.email are already configured in this repository.",
    }


def seed_item(queue: Path, marker: str) -> Path:
    path = queue / turn.ITEMS / f"{turn.new_item_id()}.jsonl"
    turn.append(path, backlog.ITEM, {"event": "created", "loop": "receipt", "frame": frame_for(marker)}, actor="receipt")
    return path


def trailers(repo: Path, *, rev: str = "HEAD") -> str:
    return git(repo, "log", "-1", "--format=%(trailers)", rev)


def tool_calls(transcript_path: Path, name: str) -> list[dict[str, Any]]:
    """Every `tool_use` block the agent actually issued for `name`, read from its own stream.

    Used to tell "the agent read the vocabulary" from "the agent guessed right" -- a passing
    `Outcome.ADVANCED` is consistent with either, and only the transcript can distinguish them
    (teach-event-vocabulary/proposal.md - Decision 1's accepted risk).
    """
    calls: list[dict[str, Any]] = []
    for line in transcript_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        event = json.loads(line)
        if event.get("type") != "assistant":
            continue
        for block in event.get("message", {}).get("content", []):
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == name:
                calls.append(block.get("input", {}))
    return calls


def test_take_turn_drives_a_real_agent_against_a_real_foreign_workspace(queue: Path, workspace: Path) -> None:
    """Receipts 1-4: queue != workspace, a real executor, the ledger row, both commit trailers.

    `Outcome.FAILED` is the expected, asserted outcome here -- not a lowered bar. The agent does the
    real work (checked below, from the workspace's own git log) and then cannot legally report it,
    because nothing teaches it the event vocabulary (module docstring, and proposal.md - Finding).
    That refusal is `take_turn` working correctly, not a defect this receipt is failing to catch.
    """
    marker = f"receipt-{uuid.uuid4().hex[:8]}"
    seed_item(queue, marker)

    record = turn.take_turn(
        places(queue, workspace),
        real_executor,
        limits=LIMITS,
        owner="yf9-receipt",
        skill=SKILL,
        planning_frame=turn.DEFAULT_PLANNING_FRAME,
        proposal_dir=queue.parent,
        isolated=False,
    )

    assert record.outcome is Outcome.FAILED, record.note

    # Receipt 2: the workspace received the agent's own commit, and no queue bookkeeping leaked in.
    assert marker in (workspace / "notes.txt").read_text(encoding="utf-8")
    assert git(workspace, "log", "--oneline").count("\n") >= 1  # more than the seed commit alone
    assert not (workspace / "backlog").exists()
    assert not (workspace / "questions").exists()
    assert not (workspace / "ledger").exists()

    # Receipt 3: the ledger row exists in the queue and names the record's own run_id.
    ledger_matches = list((queue / turn.RUNS).glob(f"*-{record.run_id}.json"))
    assert len(ledger_matches) == 1
    on_disk = json.loads(ledger_matches[0].read_text(encoding="utf-8"))
    assert on_disk["run_id"] == record.run_id

    # Receipt 4: both trailers, read structurally -- never string-matched against the message.
    body = trailers(queue)
    assert f"Co-Authored-By: {turn.PLATFORM_CO_AUTHOR}" in body
    assert f"{turn.RUN_TRAILER_KEY}: {record.run_id}" in body


def test_a_real_agent_reaches_done_once_the_vocabulary_is_reachable(queue: Path, workspace: Path) -> None:
    """Receipt 7, `teach-event-vocabulary`'s deferred scope: the `done` path itself, driven for real.

    `test_command=("true",)` -- the throwaway workspace has no pytest suite, so the default gate
    command (`pytest -q`) would fail `verify.may_write_done` for a reason unrelated to the vocabulary
    fix (see the two tests above, and the module docstring). This does not weaken the gate: a
    workspace with a real test suite still gets `verify.DEFAULT_TEST_COMMAND` unless its own caller
    overrides it, exactly as before this change.
    """
    marker = f"receipt-{uuid.uuid4().hex[:8]}"
    item_path = seed_item(queue, marker)

    record = turn.take_turn(
        places(queue, workspace),
        real_executor,
        limits=LIMITS,
        owner="yf9-receipt",
        skill=SKILL,
        proposal_dir=queue.parent,
        isolated=False,
        test_command=("true",),
    )

    assert record.outcome is Outcome.ADVANCED, record.note

    # The item's own trail carries the done event, with the fields the vocabulary requires.
    lines = [json.loads(line) for line in item_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    last = lines[-1]
    assert last["event"] == "done"
    assert last.get("effects")
    assert last.get("verified_by")

    # The workspace really did receive the agent's own commit.
    assert marker in (workspace / "notes.txt").read_text(encoding="utf-8")

    # Not luck: the agent's own stream shows it read the vocabulary pointer this change wired in,
    # before it ever wrote the proposal -- distinguishing "read the spec" from "guessed right".
    transcript_path = places(queue, workspace).ledger / f"{record.run_id}.stream.jsonl"
    assert transcript_path.exists()
    reads = tool_calls(transcript_path, "Read")
    read_paths = {call.get("file_path") for call in reads}
    assert str(backlog.VOCABULARY_SPEC) in read_paths


def test_two_turns_share_a_byte_identical_co_author_and_independent_run_ids(queue: Path, workspace: Path) -> None:
    """Receipt 5: the property no unit test can stand in for -- a unit test asserts the id it made.

    Both turns are expected to end `FAILED`, for the same reason as the test above. `_finish` commits
    unconditionally, so the trailer comparison is meaningful regardless of outcome.
    """
    marker_one = f"receipt-{uuid.uuid4().hex[:8]}"
    seed_item(queue, marker_one)
    first = turn.take_turn(
        places(queue, workspace),
        real_executor,
        limits=LIMITS,
        owner="yf9-receipt",
        skill=SKILL,
        proposal_dir=queue.parent,
        isolated=False,
    )
    assert first.outcome is Outcome.FAILED, first.note
    first_trailer = trailers(queue)

    marker_two = f"receipt-{uuid.uuid4().hex[:8]}"
    seed_item(queue, marker_two)
    second = turn.take_turn(
        places(queue, workspace),
        real_executor,
        limits=LIMITS,
        owner="yf9-receipt",
        skill=SKILL,
        proposal_dir=queue.parent,
        isolated=False,
    )
    assert second.outcome is Outcome.FAILED, second.note
    second_trailer = trailers(queue)

    assert first.run_id != second.run_id

    def co_author_line(body: str) -> str:
        lines = [line for line in body.splitlines() if line.startswith("Co-Authored-By: yosefactory")]
        assert len(lines) == 1
        return lines[0]

    assert co_author_line(first_trailer) == co_author_line(second_trailer)


def test_a_turn_that_crashes_before_commit_leaves_a_legible_gap(queue: Path, tmp_path: Path) -> None:
    """Receipt 6: `.start` is committed before the executor ever runs, so a real crash leaves a gap.

    Triggered for real, not mocked, and genuinely free: `Places.workspace` names a path that is a
    regular *file*, not a directory. `_workspace_lock`'s `single_flight(workspace_lock)` does
    `lock_path.parent.mkdir(parents=True, exist_ok=True)` before anything else runs, and that raises
    `NotADirectoryError` immediately -- no subprocess is ever spawned.

    A first version of this test pointed `workspace` at a path that simply did not exist, expecting
    `subprocess.Popen(cwd=<missing>)` to fail. It did not: that same `mkdir(parents=True)` *creates*
    the missing directory as a side effect of taking the lock, so `Popen` found a directory (empty,
    not a git repository) and a real `claude` process ran against it -- $0.71 spent discovering this,
    on a real run that correctly reported the workspace was not a git repository and then correctly
    got refused for proposing an event planning does not accept. Real money, a real surprise, caught
    by checking the subject (the ledger's own `.json` record, not this test's expectation) rather than
    trusting the first version's docstring. Left here as the reason this version exists.
    """
    not_a_directory = tmp_path / "not-a-directory"
    not_a_directory.write_text("a plain file, not a workspace", encoding="utf-8")
    broken_places = places(queue, not_a_directory)

    with pytest.raises(NotADirectoryError):
        turn.take_turn(
            broken_places,
            real_executor,
            limits=LIMITS,
            owner="yf9-receipt",
            skill=SKILL,
            proposal_dir=queue.parent,
        )

    starts = sorted((queue / turn.RUNS).glob("*.start"))
    records = sorted((queue / turn.RUNS).glob("*.json"))
    assert len(starts) == 1
    assert len(records) == 0

    slug = starts[0].stem
    assert slug in git(queue, "show", "HEAD", "--stat")

    window = read_window(queue / turn.RUNS, 5)
    gap = next(position for position in window if position.slug == slug)
    assert gap.is_gap is True
    assert gap.outcome is Outcome.FAILED


def test_the_wrapper_matches_the_executor_protocol() -> None:
    """A cheap, offline check that `real_executor`'s signature is what `take_turn` will call."""
    import inspect

    sig = inspect.signature(real_executor)
    assert list(sig.parameters) == ["frame", "workspace", "limits", "run_id", "runs_dir", "invocation"]
