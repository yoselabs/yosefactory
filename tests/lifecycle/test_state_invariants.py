"""ADR-0005 invariants I1-I8 — contract tests against GitFileStateStorage.

One test (or test class) per invariant. Where the invariant is an
orchestration concern enforced by dispatch (P4+) rather than by the
storage layer itself, the test is skipped with a clear pointer at the
phase that owns enforcement — the invariant is still named in code, so
a future refactor that breaks it shows up in a review somewhere.
"""

from __future__ import annotations

import json

import pytest

from a2sdlc.domain.exceptions import StateSchemaRegression, StateSchemaTooNew
from a2sdlc.domain.models import StageName, TicketState
from a2sdlc.lifecycle.state import StateManager
from a2sdlc.lifecycle.state_storage import GitFileStateStorage
from tests.fakes import FakeGitAdapter


def _make_state(**kwargs: object) -> TicketState:
    defaults: dict[str, object] = {
        "stage": StageName.SPEC,
        "branch": "a2sdlc/PROJ-1",
        "stage_run_id": "run-1",
        "last_updated": "2026-04-24T00:00:00Z",
    }
    defaults.update(kwargs)
    return TicketState(**defaults)  # ty: ignore[invalid-argument-type]


@pytest.mark.unit
class TestI1ReadAfterBranchSetup:
    """I1 — state is read only after git.setup_branch() has succeeded.

    Enforced by dispatch ordering (see commit a78b404). The storage layer
    itself has no notion of branch state; it trusts the caller. P4 lifts
    this invariant into gating/ so it is structurally enforced, not
    positional.
    """

    @pytest.mark.skip(reason="orchestration invariant — enforced by P4 (gating/)")
    def test_read_after_branch_setup(self) -> None:
        pass


@pytest.mark.unit
class TestI2WriteOnTicketBranch:
    """I2 — state written on ticket branch, never on base branch.

    Enforced by dispatch ordering + base-branch cleanup (see commit
    24abaf8). The storage layer trusts the caller that the correct
    branch is checked out. P4 lifts this into gating/.
    """

    @pytest.mark.skip(
        reason="orchestration invariant — enforced by P4 (gating/) and "
        "git adapter's branch-state knowledge",
    )
    def test_write_requires_ticket_branch(self) -> None:
        pass


@pytest.mark.unit
class TestI3AllowlistedCommitPaths:
    """I3 — state writes commit only allowlisted paths.

    Storage layer's contract: write_state() writes the state blob, nothing
    else. Commit/push is an adjacent GitAdapter concern. The storage does
    not leak unexpected writes.
    """

    def test_write_state_calls_only_git_write_state(self) -> None:
        git = FakeGitAdapter()
        storage = GitFileStateStorage(git)
        storage.write("PROJ-1", '{"stage":"spec"}')

        # Storage only touched write_state. No commit/push/branch calls.
        assert len(git.written_state) == 1
        assert git.commits == []
        assert git.pushes == []
        assert git.branch_setups == []

    def test_runtime_artifact_scrub_happens_via_dedicated_method(self) -> None:
        # GitAdapter exposes strip_runtime_state() for pre-merge cleanup
        # (the second half of the I2 fix). Storage does NOT call it.
        git = FakeGitAdapter()
        storage = GitFileStateStorage(git)
        storage.write("PROJ-1", '{"stage":"spec"}')
        assert git.state_strips == 0


@pytest.mark.unit
class TestI4BaseCleanupAfterMerge:
    """I4 — base branch cleanup runs after merge.

    Orchestration invariant. Implemented via GitAdapter.strip_runtime_state
    called by the MERGE stage (P2 promotion) + dispatch ordering. Storage
    has no role here.
    """

    @pytest.mark.skip(reason="orchestration invariant — enforced by MERGE stage (P2)")
    def test_base_cleanup_after_merge(self) -> None:
        pass


@pytest.mark.unit
class TestI5StageRunIdUniqueness:
    """I5 — stage_run_id is unique per dispatch invocation.

    Derivation invariant — stage_run_id is deterministically derived per
    composition profile (see pipeline's _derive_mode2_run_id). Storage
    just persists whatever it's handed. Uniqueness lives upstream.
    """

    @pytest.mark.skip(
        reason="derivation invariant — enforced by run_id derivation logic in pipeline/",
    )
    def test_stage_run_id_uniqueness(self) -> None:
        pass


@pytest.mark.unit
class TestI6ConcurrencyViaCI:
    """I6 — concurrent writes serialized by CI concurrency group, not in-engine locking.

    This is a declaration of the concurrency model. The test asserts the
    storage does NOT try to acquire its own lock — if a future refactor
    adds file-locking or a mutex, this test fails, forcing a conscious
    ADR-0005 revisit.
    """

    def test_storage_does_not_acquire_locks(self) -> None:
        # GitFileStateStorage is a thin pass-through to GitAdapter methods.
        # Two successive writes must both land without any blocking call.
        git = FakeGitAdapter()
        storage = GitFileStateStorage(git)
        storage.write("PROJ-1", '{"stage":"spec"}')
        storage.write("PROJ-1", '{"stage":"implement"}')
        assert len(git.written_state) == 2

    def test_storage_has_no_lock_attributes(self) -> None:
        # Surface-level assertion: no suspicious attributes hinting at
        # lock/mutex state. Catches a future refactor that adds one
        # without documenting the model change.
        storage = GitFileStateStorage(FakeGitAdapter())
        for name in ("_lock", "lock", "_mutex", "mutex", "_semaphore"):
            assert not hasattr(storage, name), (
                f"GitFileStateStorage must not carry {name!r} — I6 says "
                "serialization is CI-level, not in-engine"
            )


@pytest.mark.unit
class TestI7SchemaVersionMonotonic:
    """I7 — schema_version monotonically increases within a ticket's lifetime.

    Enforced at the StateManager layer. Downgrades raise
    StateSchemaRegression. See also TestSchemaVersioning in test_state.py.
    """

    def test_downgrade_rejected(self) -> None:
        v2_raw = (
            '{"schema_version":2,"stage":"spec","branch":"a2sdlc/X",'
            '"stage_run_id":"r","last_updated":"2026-04-24T00:00:00Z"}'
        )
        git = FakeGitAdapter(state_json=v2_raw)
        sm = StateManager(GitFileStateStorage(git), "PROJ-1")

        downgraded = _make_state()
        downgraded.schema_version = 1  # type: ignore[misc]

        with pytest.raises(StateSchemaRegression):
            sm.write_state(downgraded)

    def test_future_version_on_read_raises(self) -> None:
        future_raw = (
            '{"schema_version":999,"stage":"spec","branch":"a2sdlc/X",'
            '"stage_run_id":"r","last_updated":"2026-04-24T00:00:00Z"}'
        )
        git = FakeGitAdapter(state_json=future_raw)
        sm = StateManager(GitFileStateStorage(git), "PROJ-1")

        with pytest.raises(StateSchemaTooNew):
            sm.read_state()


@pytest.mark.unit
class TestI8ReadModifyWriteSafety:
    """I8 — StateStorage impls must be read-modify-write safe.

    The Protocol does not promise atomicity, but each impl documents its
    consistency model (GitFileStateStorage: checked-out branch scopes
    visibility; concurrency handled by CI group per I6).

    The concrete testable contract today is: unknown fields survive a
    read-modify-write round trip. Without that, a newer writer's fields
    silently vanish when an older reader re-writes the state.
    """

    def test_unknown_fields_round_trip(self) -> None:
        # Simulate a v3 field in persisted state; a v2 engine reads,
        # modifies an unrelated field, and writes back.
        original = {
            "schema_version": 2,
            "stage": "spec",
            "branch": "a2sdlc/X",
            "stage_run_id": "r",
            "last_updated": "2026-04-24T00:00:00Z",
            "future_v3_field": "must-survive",
        }
        git = FakeGitAdapter(state_json=json.dumps(original))
        sm = StateManager(GitFileStateStorage(git), "PROJ-1")

        state = sm.read_state()
        assert state is not None

        # Modify a normal field and write back.
        state.review_cycles = state.review_cycles + 1
        sm.write_state(state)

        # Read back and confirm unknown field preserved.
        assert len(git.written_state) == 1
        restored_raw = json.loads(git.written_state[0])
        assert restored_raw.get("future_v3_field") == "must-survive"

    def test_impl_documents_consistency_model(self) -> None:
        # I8 names this as a soft contract — each impl must document.
        # GitFileStateStorage's docstring references the branch-scoped
        # consistency model.
        assert GitFileStateStorage.__doc__ is not None
        assert "branch" in GitFileStateStorage.__doc__.lower()
