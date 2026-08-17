"""The repo's own directories are found by marker, so no module's depth under the root is load-bearing."""

from __future__ import annotations

from pathlib import Path

import pytest

from yosefactory.paths import RepoRootNotFound, repo_root
from yosefactory.protocol.backlog import VOCABULARY_SPEC
from yosefactory.runtime.spend import SPEND_LOG

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("marker", ["pyproject.toml", ".git"])
def test_the_nearest_marker_wins_at_any_depth(tmp_path: Path, marker: str) -> None:
    (tmp_path / marker).touch()
    deep = tmp_path / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    assert repo_root(deep / "module.py") == tmp_path


def test_an_inner_checkout_is_not_mistaken_for_its_container(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").touch()
    inner = tmp_path / "vendored"
    inner.mkdir()
    (inner / ".git").touch()
    assert repo_root(inner / "src" / "module.py") == inner


def test_no_marker_anywhere_raises_rather_than_guessing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Installed apart from its source tree there is no `openspec/` or `ledger/` to name, and a path
    invented anyway fails later, somewhere that cannot say why."""
    monkeypatch.setattr(Path, "exists", lambda self: False)
    with pytest.raises(RepoRootNotFound):
        repo_root(tmp_path / "src" / "yosefactory" / "paths.py")


def test_both_call_sites_resolve_into_this_checkout() -> None:
    assert VOCABULARY_SPEC == ROOT / "openspec" / "specs" / "backlog-item-format" / "spec.md"
    assert VOCABULARY_SPEC.is_file()
    assert SPEND_LOG == ROOT / "ledger" / "spend.jsonl"
    assert SPEND_LOG.parent.is_dir()
