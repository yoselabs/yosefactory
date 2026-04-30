"""Lazy v0 -> v1 state migration."""

from __future__ import annotations

import logging

from a2sdlc.runtime.state_migration import V1_SCHEMA_VERSION, migrate_state_blob


def test_v0_blob_gains_schema_version_one() -> None:
    v0 = {"branch": "a2sdlc/foo", "stage": "SPEC"}
    migrated, did_migrate = migrate_state_blob(v0)
    assert did_migrate is True
    assert migrated["schema_version"] == V1_SCHEMA_VERSION


def test_v0_blob_gets_default_ecosystem_local() -> None:
    v0 = {"branch": "a2sdlc/foo", "stage": "SPEC"}
    migrated, _ = migrate_state_blob(v0)
    assert migrated["ecosystem"] == "local"


def test_v1_blob_passes_through_untouched() -> None:
    v1 = {"branch": "a2sdlc/foo", "schema_version": 1, "ecosystem": "local"}
    migrated, did_migrate = migrate_state_blob(v1)
    assert did_migrate is False
    assert migrated == v1


def test_migration_emits_log_line(caplog) -> None:
    caplog.set_level(logging.INFO, logger="a2sdlc.runtime.state_migration")
    migrate_state_blob({"branch": "x", "stage": "SPEC"})
    assert any("state.migrated from=v0 to=v1" in r.message for r in caplog.records)
