"""Tests for TicketState schema migrations (ADR-0005)."""

from __future__ import annotations

import pytest

from a2sdlc.domain.exceptions import StateSchemaTooNew
from a2sdlc.lifecycle.state_migrations import (
    CURRENT_SCHEMA_VERSION,
    apply_migrations,
    migrate_v1_to_v2,
)


@pytest.mark.unit
class TestMigrateV1ToV2:
    def test_adds_v2_defaults(self) -> None:
        v1 = {
            "stage": "spec",
            "branch": "a2sdlc/TEST-1",
            "stage_run_id": "run-001",
            "last_updated": "2026-04-24T00:00:00Z",
        }
        v2 = migrate_v1_to_v2(v1)

        assert v2["schema_version"] == 2
        assert v2["parent_key"] is None
        assert v2["children"] == []
        assert v2["child_outcomes"] == {}
        assert v2["revisions"] == 0
        assert v2["engine_version"] == ""
        assert v2["workflow_name"] == "default"
        assert v2["rate_limited_until"] is None

    def test_does_not_clobber_existing_fields(self) -> None:
        v1 = {
            "stage": "spec",
            "branch": "a2sdlc/TEST-1",
            "stage_run_id": "run-001",
            "last_updated": "2026-04-24T00:00:00Z",
            "parent_key": "EPIC-1",
            "children": ["C-1"],
            "engine_version": "0.1.0+abc",
        }
        v2 = migrate_v1_to_v2(v1)

        assert v2["parent_key"] == "EPIC-1"
        assert v2["children"] == ["C-1"]
        assert v2["engine_version"] == "0.1.0+abc"

    def test_preserves_v1_semantics(self) -> None:
        # v1 fields pass through unchanged.
        v1 = {
            "stage": "implement",
            "branch": "a2sdlc/TEST-1",
            "stage_run_id": "run-001",
            "last_updated": "2026-04-24T00:00:00Z",
            "pr_number": 42,
            "review_cycles": 3,
            "accumulated_cost_usd": 1.5,
        }
        v2 = migrate_v1_to_v2(v1)

        assert v2["pr_number"] == 42
        assert v2["review_cycles"] == 3
        assert v2["accumulated_cost_usd"] == 1.5


@pytest.mark.unit
class TestApplyMigrations:
    def test_missing_schema_version_treated_as_v1(self) -> None:
        v1_document = {
            "stage": "spec",
            "branch": "a2sdlc/X",
            "stage_run_id": "r",
            "last_updated": "2026-04-24T00:00:00Z",
        }
        migrated = apply_migrations(v1_document)
        assert migrated["schema_version"] == CURRENT_SCHEMA_VERSION

    def test_already_current_is_no_op(self) -> None:
        v2_document = {
            "schema_version": 2,
            "stage": "spec",
            "branch": "a2sdlc/X",
            "stage_run_id": "r",
            "last_updated": "2026-04-24T00:00:00Z",
            "parent_key": None,
            "children": [],
        }
        migrated = apply_migrations(v2_document)
        assert migrated == v2_document

    def test_future_version_raises_state_schema_too_new(self) -> None:
        v3_document = {
            "schema_version": 3,
            "stage": "spec",
            "branch": "a2sdlc/X",
            "stage_run_id": "r",
            "last_updated": "2026-04-24T00:00:00Z",
        }
        with pytest.raises(StateSchemaTooNew) as excinfo:
            apply_migrations(v3_document)
        assert excinfo.value.found == 3
        assert excinfo.value.supported == CURRENT_SCHEMA_VERSION
