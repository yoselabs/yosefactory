"""The workspace's own configuration: `.factory/config.json`, on the default branch, at its tip.

This module owns *what the file means* -- schema, parsing, validation, defaults, version handling,
error messages. It does not own *which copy of the file counts*: resolving "the default branch's
tip" is forge-specific and belongs to the caller, the same line `BoardAdapter` draws and for the
same reason (`board/adapter.py`). This module therefore takes a path or file contents, never a
repository and never a ref.

**Refuse by default.** A missing file, unparseable JSON, an unknown `version`, a malformed `users`,
or an empty `allowed` list all mean nobody is allowed. `users.allowed` is a security boundary --
who may cause this factory to spend quota on a public repository's traffic -- and an error that
degraded to "permit everything" would be the defect the allowlist exists to prevent. Every failure
here raises `WorkspaceConfigError` rather than returning a config with no allowed actors, so a bug
that lets a broken config slip past a caller's error handling still fails loudly instead of quietly
opening the gate.

`version` exists so an incompatible future shape is refused rather than misread, the same posture as
`protocol/eventlog.py`'s unknown-event rule: silently reinterpreting a shape as if it were the one
this module understands would report a set of allowed actors that never existed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

SUPPORTED_VERSION: Final = 1


class WorkspaceConfigError(ValueError):
    """The workspace config could not be loaded. Every case this raises for means "refuse", not
    "assume a default" -- callers must not catch this and substitute an unrestricted allowlist."""


@dataclass(frozen=True, slots=True)
class WorkspaceConfig:
    version: int
    allowed_actors: frozenset[str]


def load(path: Path) -> WorkspaceConfig:
    """Load and validate the workspace config at `path`.

    `path` is a plain filesystem path, resolved by the caller -- this function does not know or
    care whether it sits on a default branch, a clone, or a checkout of some other ref.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise WorkspaceConfigError(f"{path}: cannot be read ({exc})") from exc
    return loads(text, source=str(path))


def loads(text: str, *, source: str = "<config>") -> WorkspaceConfig:
    """Parse and validate workspace config text already in hand -- the same rules `load` applies,
    for a caller that already has the file's contents (e.g. read through a forge API rather than
    off a local checkout)."""
    try:
        raw: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WorkspaceConfigError(f"{source}: not valid JSON ({exc.msg})") from exc
    if not isinstance(raw, dict):
        raise WorkspaceConfigError(f"{source}: expected a JSON object, found {type(raw).__name__}")

    version = raw.get("version")
    if version != SUPPORTED_VERSION:
        raise WorkspaceConfigError(f"{source}: unsupported version {version!r}, expected {SUPPORTED_VERSION!r}")

    users = raw.get("users")
    if not isinstance(users, dict):
        raise WorkspaceConfigError(f"{source}: 'users' must be an object, found {type(users).__name__}")

    allowed = users.get("allowed")
    if not isinstance(allowed, list) or not allowed or not all(isinstance(login, str) and login for login in allowed):
        raise WorkspaceConfigError(f"{source}: 'users.allowed' must be a non-empty list of non-empty strings")

    return WorkspaceConfig(version=version, allowed_actors=frozenset(allowed))
