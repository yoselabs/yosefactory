"""TicketState schema migrations per ADR-0005.

Each migration is a pure ``dict -> dict`` function. ``apply_migrations``
routes a persisted document forward to ``CURRENT_SCHEMA_VERSION``. Raises
``StateSchemaTooNew`` if the document is ahead of what this engine
supports (ADR-0005 backward-incompat rule).

Moves to ``session/`` in the P7 relocate pass; kept under ``lifecycle/``
here to minimize diffs for P1.
"""

from __future__ import annotations

from typing import Callable

from a2sdlc.domain.exceptions import StateSchemaTooNew

CURRENT_SCHEMA_VERSION = 2


def migrate_v1_to_v2(data: dict) -> dict:
    """Add v2 default fields to a v1-shape document.

    v1 documents lack ``schema_version`` entirely; v2 adds it plus the N2
    subtask fields, N5 placeholders, observability fields, and the rate-
    limit self-heal slot (architecture vision §2.23).
    """
    migrated = dict(data)
    migrated.setdefault("schema_version", 2)
    migrated.setdefault("parent_key", None)
    migrated.setdefault("children", [])
    migrated.setdefault("child_outcomes", {})
    migrated.setdefault("revisions", 0)
    migrated.setdefault("engine_version", "")
    migrated.setdefault("workflow_name", "default")
    migrated.setdefault("rate_limited_until", None)
    return migrated


# Migrations keyed by source version. Each returns a document at source + 1.
_MIGRATIONS: dict[int, Callable[[dict], dict]] = {
    1: migrate_v1_to_v2,
}


def apply_migrations(data: dict) -> dict:
    """Route ``data`` to ``CURRENT_SCHEMA_VERSION``.

    Missing ``schema_version`` is treated as v1 (pre-ADR-0005 documents).
    Raises ``StateSchemaTooNew`` if the document's version is ahead of
    what this engine supports.
    """
    version = data.get("schema_version", 1)
    if version > CURRENT_SCHEMA_VERSION:
        raise StateSchemaTooNew(found=version, supported=CURRENT_SCHEMA_VERSION)
    migrated = data
    while version < CURRENT_SCHEMA_VERSION:
        migrate = _MIGRATIONS[version]
        migrated = migrate(migrated)
        version = migrated.get("schema_version", version + 1)
    return migrated


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "apply_migrations",
    "migrate_v1_to_v2",
]
