"""Duplicate / similar symbol detector for a2sdlc Python source.

Walks packages/*/src/**/*.py, extracts top-level exported symbols
(functions, classes, type aliases), groups them by name similarity,
and writes a markdown summary + JSON report.

Advisory only — always exits 0.
"""

from __future__ import annotations

import ast
import re
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


_PREFIXES: frozenset[str] = frozenset(
    {
        "get",
        "set",
        "create",
        "make",
        "build",
        "fetch",
        "load",
        "update",
        "delete",
        "remove",
        "handle",
        "parse",
        "format",
        "ensure",
        "is",
        "has",
        "to",
        "from",
        "run",
        "do",
    }
)

_SUFFIXES: frozenset[str] = frozenset(
    {
        "handler",
        "service",
        "factory",
        "provider",
        "context",
        "config",
        "schema",
        "result",
        "response",
        "request",
        "input",
        "output",
        "options",
        "stage",
        "adapter",
    }
)


def _split_identifier(name: str) -> list[str]:
    # snake_case / kebab-case → spaces
    s = re.sub(r"[_-]+", " ", name)
    # camelCase / PascalCase boundaries
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    return [w for w in s.lower().split() if w]


def normalize_name(name: str) -> str:
    words = _split_identifier(name)
    if not words:
        return ""
    start = 0
    end = len(words)
    # Alternately strip leading prefixes and trailing suffixes until stable,
    # but never reduce to zero words.
    changed = True
    while changed:
        changed = False
        if end - start > 1 and words[end - 1] in _SUFFIXES:
            end -= 1
            changed = True
        if end - start > 1 and words[start] in _PREFIXES:
            start += 1
            changed = True
    final = words[start:end]
    return "".join(final if final else words)


def jaro_winkler(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0

    match_distance = max(len(a), len(b)) // 2 - 1
    a_matches = [False] * len(a)
    b_matches = [False] * len(b)
    matches = 0

    for i, ca in enumerate(a):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len(b))
        for j in range(start, end):
            if b_matches[j] or b[j] != ca:
                continue
            a_matches[i] = True
            b_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    # Transpositions
    t = 0
    k = 0
    for i, _ in enumerate(a):
        if not a_matches[i]:
            continue
        while not b_matches[k]:
            k += 1
        if a[i] != b[k]:
            t += 1
        k += 1
    transpositions = t / 2

    jaro = (
        matches / len(a) + matches / len(b) + (matches - transpositions) / matches
    ) / 3

    # Winkler boost for up to 4-char common prefix
    prefix = 0
    for i in range(min(4, len(a), len(b))):
        if a[i] == b[i]:
            prefix += 1
        else:
            break
    return jaro + prefix * 0.1 * (1 - jaro)


JW_THRESHOLD = 0.9
JW_MIN_LEN = 4


@dataclass(frozen=True)
class Group:
    normalized_name: str
    similarity: Literal["normalized-match", "jaro-winkler"]
    items: tuple[Item, ...]


def _item_key(i: Item) -> str:
    return f"{i.path}:{i.line}:{i.name}"


def group_items(items: list[Item]) -> list[Group]:
    by_norm: dict[str, list[Item]] = {}
    for it in items:
        norm = normalize_name(it.name)
        if not norm:
            continue
        by_norm.setdefault(norm, []).append(it)

    groups: list[Group] = []
    claimed: set[str] = set()

    # Pass 1: exact-normalized collisions
    for norm, bucket in by_norm.items():
        if len(bucket) < 2:
            continue
        groups.append(
            Group(
                normalized_name=norm,
                similarity="normalized-match",
                items=tuple(bucket),
            )
        )
        for it in bucket:
            claimed.add(_item_key(it))

    # Pass 2: Jaro-Winkler over remaining singletons
    remaining = [
        (norm, bucket[0])
        for norm, bucket in by_norm.items()
        if len(bucket) == 1 and _item_key(bucket[0]) not in claimed
    ]

    for i, (norm_a, item_a) in enumerate(remaining):
        if _item_key(item_a) in claimed:
            continue
        if len(norm_a) < JW_MIN_LEN:
            continue
        cluster: list[Item] = [item_a]
        for j in range(i + 1, len(remaining)):
            norm_b, item_b = remaining[j]
            if _item_key(item_b) in claimed:
                continue
            if len(norm_b) < JW_MIN_LEN:
                continue
            if jaro_winkler(norm_a, norm_b) >= JW_THRESHOLD:
                cluster.append(item_b)
                claimed.add(_item_key(item_b))
        if len(cluster) >= 2:
            claimed.add(_item_key(item_a))
            groups.append(
                Group(
                    normalized_name=norm_a,
                    similarity="jaro-winkler",
                    items=tuple(cluster),
                )
            )

    # Sort: largest group first, then alphabetical
    groups.sort(key=lambda g: (-len(g.items), g.normalized_name))

    # Sort items within each group by (path, line)
    groups = [
        Group(
            normalized_name=g.normalized_name,
            similarity=g.similarity,
            items=tuple(sorted(g.items, key=lambda i: (i.path, i.line))),
        )
        for g in groups
    ]

    return groups
