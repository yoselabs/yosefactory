"""Refuse-by-default: every malformed shape means nobody is allowed, not "permit everything"."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from yosefactory.protocol.workspace_config import WorkspaceConfigError, load, loads

VALID = '{"version": 1, "users": {"allowed": ["denis", "iorlas"]}}'


def test_a_valid_config_loads() -> None:
    config = loads(VALID)

    assert config.version == 1
    assert config.allowed_actors == frozenset({"denis", "iorlas"})


def test_load_reads_a_file(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(VALID, encoding="utf-8")

    config = load(path)

    assert config.allowed_actors == frozenset({"denis", "iorlas"})


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceConfigError, match="cannot be read"):
        load(tmp_path / "does-not-exist.json")


def test_unparseable_json_is_refused() -> None:
    with pytest.raises(WorkspaceConfigError, match="not valid JSON"):
        loads("{not json")


def test_a_json_array_is_refused() -> None:
    with pytest.raises(WorkspaceConfigError, match="expected a JSON object"):
        loads("[]")


def test_a_missing_version_is_refused() -> None:
    with pytest.raises(WorkspaceConfigError, match="unsupported version"):
        loads('{"users": {"allowed": ["denis"]}}')


def test_an_unknown_version_is_refused() -> None:
    with pytest.raises(WorkspaceConfigError, match="unsupported version"):
        loads('{"version": 2, "users": {"allowed": ["denis"]}}')


def test_a_missing_users_is_refused() -> None:
    with pytest.raises(WorkspaceConfigError, match="'users' must be an object"):
        loads('{"version": 1}')


def test_a_non_object_users_is_refused() -> None:
    with pytest.raises(WorkspaceConfigError, match="'users' must be an object"):
        loads('{"version": 1, "users": ["denis"]}')


def test_a_missing_allowed_is_refused() -> None:
    with pytest.raises(WorkspaceConfigError, match=re.escape("'users.allowed' must be")):
        loads('{"version": 1, "users": {}}')


def test_an_empty_allowed_is_refused() -> None:
    with pytest.raises(WorkspaceConfigError, match=re.escape("'users.allowed' must be")):
        loads('{"version": 1, "users": {"allowed": []}}')


def test_a_non_list_allowed_is_refused() -> None:
    with pytest.raises(WorkspaceConfigError, match=re.escape("'users.allowed' must be")):
        loads('{"version": 1, "users": {"allowed": "denis"}}')


def test_a_non_string_member_is_refused() -> None:
    with pytest.raises(WorkspaceConfigError, match=re.escape("'users.allowed' must be")):
        loads('{"version": 1, "users": {"allowed": ["denis", 1]}}')


def test_an_empty_string_member_is_refused() -> None:
    with pytest.raises(WorkspaceConfigError, match=re.escape("'users.allowed' must be")):
        loads('{"version": 1, "users": {"allowed": [""]}}')
