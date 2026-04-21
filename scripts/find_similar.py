"""Duplicate / similar symbol detector for a2sdlc Python source.

Walks packages/*/src/**/*.py, extracts top-level exported symbols
(functions, classes, type aliases), groups them by name similarity,
and writes a markdown summary + JSON report.

Advisory only — always exits 0.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ItemKind = Literal["function", "class", "type"]


@dataclass(frozen=True)
class Item:
    name: str
    path: str
    line: int
    kind: ItemKind
    signature: str


def _signature_of_function(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    parts: list[str] = []
    args = fn.args
    for a in args.args:
        if a.annotation is not None:
            parts.append(f"{a.arg}: {ast.unparse(a.annotation)}")
        else:
            parts.append(a.arg)
    params = ", ".join(parts)
    ret = f" -> {ast.unparse(fn.returns)}" if fn.returns is not None else ""
    prefix = "async " if isinstance(fn, ast.AsyncFunctionDef) else ""
    return f"{prefix}({params}){ret}"


def _count_methods(cls: ast.ClassDef) -> int:
    return sum(
        1 for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def _truncate(text: str, limit: int = 80) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _is_typealias_annotation(node: ast.AnnAssign) -> bool:
    ann = node.annotation
    if isinstance(ann, ast.Name) and ann.id == "TypeAlias":
        return True
    if isinstance(ann, ast.Attribute) and ann.attr == "TypeAlias":
        return True
    return False


def extract_from_file(file: Path, root: Path) -> list[Item]:
    """Extract top-level non-underscore symbols from a Python file.

    `root` is used to compute the item's `path` relative to the project root.
    """
    try:
        tree = ast.parse(file.read_text(), filename=str(file))
    except SyntaxError:
        return []

    rel = str(file.relative_to(root))
    items: list[Item] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            items.append(
                Item(
                    name=node.name,
                    path=rel,
                    line=node.lineno,
                    kind="function",
                    signature=_signature_of_function(node),
                )
            )
        elif isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            n_methods = _count_methods(node)
            items.append(
                Item(
                    name=node.name,
                    path=rel,
                    line=node.lineno,
                    kind="class",
                    signature=f"class with {n_methods} method{'s' if n_methods != 1 else ''}",
                )
            )
        elif isinstance(node, ast.TypeAlias):  # PEP 695
            name_node = node.name
            name = name_node.id if isinstance(name_node, ast.Name) else None
            if not name or name.startswith("_"):
                continue
            items.append(
                Item(
                    name=name,
                    path=rel,
                    line=node.lineno,
                    kind="type",
                    signature=_truncate(ast.unparse(node.value)),
                )
            )
        elif isinstance(node, ast.AnnAssign) and _is_typealias_annotation(node):
            tgt = node.target
            if not isinstance(tgt, ast.Name) or tgt.id.startswith("_"):
                continue
            if node.value is None:
                continue
            items.append(
                Item(
                    name=tgt.id,
                    path=rel,
                    line=node.lineno,
                    kind="type",
                    signature=_truncate(ast.unparse(node.value)),
                )
            )

    return items
