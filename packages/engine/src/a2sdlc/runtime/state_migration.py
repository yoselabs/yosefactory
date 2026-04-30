"""Lazy v0 -> v1 migration of the persisted state.json blob.

Spec: §Migration notes. v0 files (no schema_version field) are read into
the v1 in-memory shape with schema_version=1 set on read, and ecosystem
defaulted to "local". The migrated state is written back to disk *lazily*
— on the next stage-finish commit — never eagerly on read.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("a2sdlc.runtime.state_migration")

V1_SCHEMA_VERSION = 1


def migrate_state_blob(blob: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Return (possibly migrated blob, did_migrate).

    Operates on a copy of the input. Caller decides whether to write back.
    """
    if blob.get("schema_version") == V1_SCHEMA_VERSION:
        return blob, False
    out = dict(blob)
    out["schema_version"] = V1_SCHEMA_VERSION
    out.setdefault("ecosystem", "local")
    logger.info("state.migrated from=v0 to=v1 (branch=%s)", out.get("branch"))
    return out, True
