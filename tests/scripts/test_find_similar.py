"""Unit tests for scripts/find_similar.py."""

from __future__ import annotations

import textwrap
from pathlib import Path


import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import find_similar as fs  # noqa: E402  # ty: ignore[unresolved-import]


def _write(tmp_path: Path, rel: str, body: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body).lstrip())
    return p


def test_extract_top_level_function(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        "m.py",
        """
        def run_stage(ticket: str) -> int:
            return 1
        """,
    )
    items = fs.extract_from_file(f, root=tmp_path)
    assert len(items) == 1
    it = items[0]
    assert it.name == "run_stage"
    assert it.kind == "function"
    assert "ticket: str" in it.signature
    assert "-> int" in it.signature
    assert it.path == "m.py"
    assert it.line == 1


def test_extract_async_function(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        "m.py",
        """
        async def fetch_ticket(id: str) -> dict:
            return {}
        """,
    )
    items = fs.extract_from_file(f, root=tmp_path)
    assert len(items) == 1
    assert items[0].signature.startswith("async ")


def test_extract_class(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        "m.py",
        """
        class TicketAdapter:
            def a(self): ...
            def b(self): ...
        """,
    )
    items = fs.extract_from_file(f, root=tmp_path)
    assert len(items) == 1
    assert items[0].kind == "class"
    assert items[0].name == "TicketAdapter"
    assert items[0].signature == "class with 2 methods"


def test_extract_pep695_type(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        "m.py",
        """
        type TicketId = str
        """,
    )
    items = fs.extract_from_file(f, root=tmp_path)
    assert len(items) == 1
    assert items[0].kind == "type"
    assert items[0].name == "TicketId"
    assert items[0].signature == "str"


def test_extract_typealias_annotation(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        "m.py",
        """
        from typing import TypeAlias
        Result: TypeAlias = dict[str, int]
        """,
    )
    items = fs.extract_from_file(f, root=tmp_path)
    names = {i.name for i in items}
    assert "Result" in names


def test_skips_underscore_names(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        "m.py",
        """
        def _private(): ...
        class _Private: ...
        def public(): ...
        """,
    )
    items = fs.extract_from_file(f, root=tmp_path)
    assert {i.name for i in items} == {"public"}


def test_skips_nested_defs(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        "m.py",
        """
        class Outer:
            def method(self): ...
            class Inner: ...

        def outer_fn():
            def nested(): ...
        """,
    )
    items = fs.extract_from_file(f, root=tmp_path)
    assert {i.name for i in items} == {"Outer", "outer_fn"}


def test_truncates_long_type_signatures(tmp_path: Path) -> None:
    long_type = "dict[" + "str, " * 40 + "int]"
    f = _write(
        tmp_path,
        "m.py",
        f"""
        type Big = {long_type}
        """,
    )
    items = fs.extract_from_file(f, root=tmp_path)
    assert len(items[0].signature) <= 80
    assert items[0].signature.endswith("...")
