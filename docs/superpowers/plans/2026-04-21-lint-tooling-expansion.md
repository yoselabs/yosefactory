# Lint Tooling Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add jscpd (copy-paste detection), actionlint (GH Actions), a Python port of `find-similar` (duplicate/similar symbol detector), and wire `make fix` into Claude Code Stop/SubagentStop hooks.

**Architecture:** jscpd is managed via a minimal root `package.json` + pnpm lockfile. actionlint is a Go binary invoked via the same `package.json` script. Both plug into the existing `make lint` + pre-commit surface. `find_similar.py` is a pure-stdlib Python script with unit-testable helpers, surfaced via an advisory `make similar` target. Claude hooks fire `make fix` at turn-end.

**Tech Stack:** pnpm@9, jscpd@4, actionlint (Go), Python 3.12 stdlib (`ast`), pytest, `agent-harness`, pre-commit / prek.

**Source spec:** `docs/superpowers/specs/2026-04-21-lint-tooling-expansion-design.md`

---

## File Structure

**Created:**
- `package.json` — pnpm project metadata + lint script commands for jscpd & actionlint.
- `pnpm-lock.yaml` — pinned dependency lockfile, checked in.
- `.config/jscpd.json` — jscpd config (threshold, ignores, Python format).
- `.claude/settings.json` — shared Claude Code hook config (Stop + SubagentStop → `make fix`).
- `scripts/find_similar.py` — duplicate/similar symbol detector. Pure stdlib. Functions testable in isolation + `main()` CLI.
- `tests/scripts/__init__.py` — empty, marks test package.
- `tests/scripts/test_find_similar.py` — unit tests for find_similar helpers.

**Modified:**
- `Makefile` — `lint` target aggregates `agent-harness lint` + `pnpm lint:jscpd` + `pnpm lint:actions`; new `similar` advisory target; `bootstrap` checks for pnpm/actionlint.
- `.pre-commit-config.yaml` — add hooks for `pnpm lint:jscpd` and `actionlint`.
- `.gitignore` — add `node_modules/` and `.similar-report.json`.

---

## Task 1: Scaffold pnpm + jscpd config files

Creates the node-side lint infrastructure without wiring it into any Make target yet. End of this task: `pnpm lint:jscpd` runs on demand and reports duplication, but nothing else has changed.

**Files:**
- Create: `package.json`
- Create: `.config/jscpd.json`
- Modify: `.gitignore` (append)

- [ ] **Step 1: Verify pnpm is available**

Run: `pnpm --version`
Expected: prints a version like `9.x.x`. If not installed, run `brew install pnpm` first.

- [ ] **Step 2: Create `package.json`**

Create `/Users/iorlas/Workspaces/a2sdlc-engine/package.json`:

```json
{
  "name": "a2sdlc-lint-tooling",
  "version": "0.0.0",
  "private": true,
  "description": "Root-level Node tooling for non-Python linters (jscpd, actionlint wrapper).",
  "packageManager": "pnpm@9.15.0",
  "scripts": {
    "lint:jscpd": "jscpd --config .config/jscpd.json",
    "lint:actions": "actionlint"
  },
  "devDependencies": {
    "jscpd": "^4.0.9"
  }
}
```

- [ ] **Step 3: Create `.config/jscpd.json`**

Create `/Users/iorlas/Workspaces/a2sdlc-engine/.config/jscpd.json`:

```json
{
  "$schema": "https://unpkg.com/jscpd@latest/schemas/jscpd.json",
  "threshold": 6,
  "reporters": ["console"],
  "absolute": false,
  "gitignore": true,
  "format": ["python"],
  "min-tokens": 50,
  "min-lines": 8,
  "ignore": [
    "**/.venv/**",
    "**/node_modules/**",
    "**/__pycache__/**",
    "**/tests/**",
    "**/*.generated.py",
    "**/coverage.xml",
    "docs/**",
    "skills/**",
    ".claude/**",
    ".similar-report.json"
  ]
}
```

- [ ] **Step 4: Add entries to `.gitignore`**

Append to `/Users/iorlas/Workspaces/a2sdlc-engine/.gitignore`:

```
# Node (for jscpd)
node_modules/

# find_similar advisory output
.similar-report.json
```

- [ ] **Step 5: Install deps and generate lockfile**

Run: `pnpm install`
Expected: creates `pnpm-lock.yaml` and `node_modules/`. No errors.

- [ ] **Step 6: Smoke-test jscpd**

Run: `pnpm lint:jscpd`
Expected: jscpd runs and prints a summary. It may or may not fail based on existing duplication — if it fails with >6% duplication, note the number but do not fix the duplication in this task. If jscpd fails only because of existing duplication, that is acceptable at this point; we will surface it in Task 12 and the user can ratchet / fix separately.

- [ ] **Step 7: Commit**

```bash
git add package.json pnpm-lock.yaml .config/jscpd.json .gitignore
git commit -m "chore(lint): scaffold pnpm + jscpd config for Python copy-paste detection"
```

---

## Task 2: Wire jscpd into `make lint` and pre-commit

**Files:**
- Modify: `Makefile` (lines 1-4)
- Modify: `.pre-commit-config.yaml` (append hook)

- [ ] **Step 1: Update `Makefile` lint target**

Replace `/Users/iorlas/Workspaces/a2sdlc-engine/Makefile` lines 1-4 (the `.PHONY` declaration and the `lint:` target):

From:
```makefile
.PHONY: lint fix test check coverage-diff security-audit arch bootstrap

lint:
	agent-harness lint
```

To:
```makefile
.PHONY: lint lint-jscpd lint-actions fix test check coverage-diff security-audit arch bootstrap similar

lint: lint-harness lint-jscpd

lint-harness:
	agent-harness lint

lint-jscpd:
	pnpm lint:jscpd
```

(Note: `lint-actions` is declared in `.PHONY` now but not yet a dependency of `lint` — wired in Task 3.)

- [ ] **Step 2: Verify `make lint` runs both steps**

Run: `make lint`
Expected: runs `agent-harness lint` first, then `pnpm lint:jscpd`. Both exit 0 (assuming no new violations from agent-harness, and <6% jscpd duplication).

- [ ] **Step 3: Add pre-commit hook for jscpd**

Append to `/Users/iorlas/Workspaces/a2sdlc-engine/.pre-commit-config.yaml` (inside the existing `hooks:` list, after `harness-lint`):

```yaml
      - id: jscpd
        name: jscpd (copy-paste detection)
        entry: pnpm lint:jscpd
        language: system
        pass_filenames: false
        always_run: true
```

- [ ] **Step 4: Test the pre-commit hook runs**

Run: `prek run jscpd --all-files` (or `pre-commit run jscpd --all-files` if prek isn't installed).
Expected: the jscpd hook executes and passes.

- [ ] **Step 5: Commit**

```bash
git add Makefile .pre-commit-config.yaml
git commit -m "chore(lint): run jscpd via make lint and pre-commit"
```

---

## Task 3: Wire actionlint into `make lint` and pre-commit

**Files:**
- Modify: `Makefile` (extend `lint` target)
- Modify: `.pre-commit-config.yaml` (append hook)

- [ ] **Step 1: Verify actionlint is installed**

Run: `actionlint --version`
Expected: prints a version. If not installed: `brew install actionlint`.

- [ ] **Step 2: Add `lint-actions` target**

In `/Users/iorlas/Workspaces/a2sdlc-engine/Makefile`, make `lint-actions` a dependency of `lint` and add the recipe. Resulting lint block:

```makefile
lint: lint-harness lint-jscpd lint-actions

lint-harness:
	agent-harness lint

lint-jscpd:
	pnpm lint:jscpd

lint-actions:
	pnpm lint:actions
```

- [ ] **Step 3: Smoke-test `make lint-actions`**

Run: `make lint-actions`
Expected: actionlint scans `.github/workflows/*.yml` and exits 0 (or reports real issues). If it reports issues, log them — fix or silence per workflow, but do not defer to a later task; workflow lint clean is a precondition for merging this work.

- [ ] **Step 4: Add pre-commit hook for actionlint scoped to workflow files**

Append to `/Users/iorlas/Workspaces/a2sdlc-engine/.pre-commit-config.yaml`:

```yaml
      - id: actionlint
        name: actionlint (GitHub Actions)
        entry: pnpm lint:actions
        language: system
        pass_filenames: false
        files: ^\.github/workflows/.*\.ya?ml$
```

`pass_filenames: false` + `files:` pattern means the hook runs only when a workflow file is staged, but actionlint itself scans the full workflow set.

- [ ] **Step 5: Verify pre-commit hook**

Run: `prek run actionlint --all-files` (or `pre-commit run actionlint --all-files`).
Expected: actionlint hook runs and passes.

- [ ] **Step 6: Commit**

```bash
git add Makefile .pre-commit-config.yaml
git commit -m "chore(lint): run actionlint via make lint and pre-commit"
```

---

## Task 4: Claude Code Stop/SubagentStop → `make fix`

**Files:**
- Create: `.claude/settings.json`

- [ ] **Step 1: Create shared Claude hook config**

Create `/Users/iorlas/Workspaces/a2sdlc-engine/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "make fix"
          }
        ]
      }
    ],
    "SubagentStop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "make fix"
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 2: Verify `make fix` is still fast**

Run: `time make fix`
Expected: completes in seconds. `make fix` is `agent-harness fix` only — it must not accidentally trigger jscpd, actionlint, or tests.

- [ ] **Step 3: Commit**

```bash
git add .claude/settings.json
git commit -m "chore(claude): run make fix on Stop and SubagentStop"
```

---

## Task 5: Update `make bootstrap`

Make bootstrap soft-check for pnpm and actionlint so new contributors get a clear hint, without hard-failing on platforms that don't have them yet.

**Files:**
- Modify: `Makefile` (bootstrap target)

- [ ] **Step 1: Replace bootstrap recipe**

In `/Users/iorlas/Workspaces/a2sdlc-engine/Makefile`, replace the existing `bootstrap:` recipe:

```makefile
bootstrap: ## First-time setup after clone
	uv sync
	agent-harness init --apply
	@if command -v pnpm >/dev/null; then pnpm install; \
	else echo "⚠  pnpm not found — install via 'brew install pnpm' to enable jscpd"; fi
	@command -v actionlint >/dev/null || echo "⚠  actionlint not found — install via 'brew install actionlint' to enable GitHub Actions lint"
	@if command -v prek >/dev/null; then prek install; \
	elif command -v pre-commit >/dev/null; then pre-commit install; \
	else echo "Install prek (brew install prek) or pre-commit for git hooks"; fi
	@echo "Done. Run 'make check' to verify."
```

- [ ] **Step 2: Smoke-test bootstrap idempotency**

Run: `make bootstrap`
Expected: all steps run cleanly; `pnpm install` says deps are up-to-date; no errors.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "chore(bootstrap): check for pnpm and actionlint with install hints"
```

---

## Task 6: `find_similar.py` — scaffold + extraction (TDD)

Begin the Python port of `find-similar`. This task builds AST-based symbol extraction. Later tasks add normalization, similarity, grouping, output.

**Files:**
- Create: `scripts/find_similar.py`
- Create: `tests/scripts/__init__.py` (empty)
- Create: `tests/scripts/test_find_similar.py`

- [ ] **Step 1: Write failing extraction tests**

Create `/Users/iorlas/Workspaces/a2sdlc-engine/tests/scripts/__init__.py` as an empty file.

Create `/Users/iorlas/Workspaces/a2sdlc-engine/tests/scripts/test_find_similar.py`:

```python
"""Unit tests for scripts/find_similar.py."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import find_similar as fs  # noqa: E402


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
```

- [ ] **Step 2: Run tests and confirm they fail**

Run: `uv run pytest tests/scripts/test_find_similar.py -v`
Expected: FAIL — `find_similar` module not found.

- [ ] **Step 3: Create the `scripts/` directory and `find_similar.py` with extraction**

Create `/Users/iorlas/Workspaces/a2sdlc-engine/scripts/find_similar.py` with the following complete content:

```python
"""Duplicate / similar symbol detector for a2sdlc Python source.

Walks packages/*/src/**/*.py, extracts top-level exported symbols
(functions, classes, type aliases), groups them by name similarity,
and writes a markdown summary + JSON report.

Advisory only — always exits 0.
"""
from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
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
```

The final file at this point contains: module docstring, imports, `ItemKind`, `Item`, the signature/count/truncate helpers, `_is_typealias_annotation`, and `extract_from_file`. Nothing else yet — later tasks append more.

- [ ] **Step 4: Run extraction tests, confirm pass**

Run: `uv run pytest tests/scripts/test_find_similar.py -v`
Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/find_similar.py tests/scripts/__init__.py tests/scripts/test_find_similar.py
git commit -m "feat(scripts): find_similar — AST-based symbol extraction"
```

---

## Task 7: `find_similar.py` — name normalization (TDD)

**Files:**
- Modify: `scripts/find_similar.py` (append)
- Modify: `tests/scripts/test_find_similar.py` (append)

- [ ] **Step 1: Write failing normalization tests**

Append to `/Users/iorlas/Workspaces/a2sdlc-engine/tests/scripts/test_find_similar.py`:

```python
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("get_ticket", "ticket"),
        ("getTicket", "ticket"),
        ("fetch_ticket_handler", "ticket"),
        ("create_stage_adapter", "stage"),
        ("TicketAdapter", "ticket"),
        ("RunResult", "run"),
        ("parseJiraResponse", "jira"),
        ("SomethingService", "something"),
        ("is_ready", "ready"),
        ("to_from_payload", "payload"),
        # Fallback: stripping would empty the name — keep original words
        ("get", "get"),
        ("handler", "handler"),
        # Multi-word kept
        ("ticket_pipeline", "ticketpipeline"),
    ],
)
def test_normalize_name(raw: str, expected: str) -> None:
    assert fs.normalize_name(raw) == expected
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `uv run pytest tests/scripts/test_find_similar.py::test_normalize_name -v`
Expected: FAIL — `normalize_name` not defined.

- [ ] **Step 3: Implement `normalize_name`**

Append to `/Users/iorlas/Workspaces/a2sdlc-engine/scripts/find_similar.py`:

```python
import re

_PREFIXES: frozenset[str] = frozenset({
    "get", "set", "create", "make", "build", "fetch", "load", "update",
    "delete", "remove", "handle", "parse", "format", "ensure",
    "is", "has", "to", "from", "run", "do",
})

_SUFFIXES: frozenset[str] = frozenset({
    "handler", "service", "factory", "provider", "context", "config",
    "schema", "result", "response", "request", "input", "output",
    "options", "stage", "adapter",
})


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
    while start < len(words) - 1 and words[start] in _PREFIXES:
        start += 1
    end = len(words)
    while end > start + 1 and words[end - 1] in _SUFFIXES:
        end -= 1
    stripped = words[start:end]
    final = stripped if stripped else words
    return "".join(final)
```

- [ ] **Step 4: Run normalization tests, confirm pass**

Run: `uv run pytest tests/scripts/test_find_similar.py::test_normalize_name -v`
Expected: all parametrized cases pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/find_similar.py tests/scripts/test_find_similar.py
git commit -m "feat(scripts): find_similar — name normalization (prefix/suffix stripping)"
```

---

## Task 8: `find_similar.py` — Jaro-Winkler similarity (TDD)

**Files:**
- Modify: `scripts/find_similar.py` (append)
- Modify: `tests/scripts/test_find_similar.py` (append)

- [ ] **Step 1: Write failing Jaro-Winkler tests**

Append to `tests/scripts/test_find_similar.py`:

```python
def test_jaro_winkler_identical() -> None:
    assert fs.jaro_winkler("abc", "abc") == 1.0


def test_jaro_winkler_empty() -> None:
    assert fs.jaro_winkler("", "abc") == 0.0
    assert fs.jaro_winkler("abc", "") == 0.0


def test_jaro_winkler_disjoint() -> None:
    # No matching characters — score should be 0
    assert fs.jaro_winkler("abc", "xyz") == 0.0


def test_jaro_winkler_known_value() -> None:
    # Classic reference: jaro_winkler("martha", "marhta") ≈ 0.961
    score = fs.jaro_winkler("martha", "marhta")
    assert 0.95 < score < 0.97


def test_jaro_winkler_prefix_boost() -> None:
    # Shared 4-char prefix triggers Winkler boost
    a = fs.jaro_winkler("ticketparse", "ticketpayload")
    b = fs.jaro_winkler("xyzparse", "xyzpayload")
    assert a > b
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `uv run pytest tests/scripts/test_find_similar.py -k jaro -v`
Expected: FAIL — `jaro_winkler` not defined.

- [ ] **Step 3: Implement `jaro_winkler`**

Append to `scripts/find_similar.py`:

```python
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
    for i, ca in enumerate(a):
        if not a_matches[i]:
            continue
        while not b_matches[k]:
            k += 1
        if ca != b[k]:
            t += 1
        k += 1
    transpositions = t / 2

    jaro = (
        matches / len(a)
        + matches / len(b)
        + (matches - transpositions) / matches
    ) / 3

    # Winkler boost for up to 4-char common prefix
    prefix = 0
    for i in range(min(4, len(a), len(b))):
        if a[i] == b[i]:
            prefix += 1
        else:
            break
    return jaro + prefix * 0.1 * (1 - jaro)
```

- [ ] **Step 4: Run Jaro-Winkler tests, confirm pass**

Run: `uv run pytest tests/scripts/test_find_similar.py -k jaro -v`
Expected: all 5 cases pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/find_similar.py tests/scripts/test_find_similar.py
git commit -m "feat(scripts): find_similar — Jaro-Winkler similarity"
```

---

## Task 9: `find_similar.py` — grouping algorithm (TDD)

**Files:**
- Modify: `scripts/find_similar.py` (append)
- Modify: `tests/scripts/test_find_similar.py` (append)

- [ ] **Step 1: Write failing grouping tests**

Append to `tests/scripts/test_find_similar.py`:

```python
def _mk(name: str, path: str = "x.py", line: int = 1) -> fs.Item:
    return fs.Item(name=name, path=path, line=line, kind="function", signature="()")


def test_group_normalized_match() -> None:
    items = [
        _mk("get_ticket", "a.py", 1),
        _mk("fetch_ticket_handler", "b.py", 2),
        _mk("unrelated_name_xyz", "c.py", 3),
    ]
    groups = fs.group_items(items)
    # Both "get_ticket" and "fetch_ticket_handler" normalize to "ticket"
    assert len(groups) == 1
    g = groups[0]
    assert g.similarity == "normalized-match"
    assert g.normalized_name == "ticket"
    assert {i.name for i in g.items} == {"get_ticket", "fetch_ticket_handler"}


def test_group_jaro_winkler_cluster() -> None:
    # Two singleton-normalized names with high JW similarity
    items = [
        _mk("ticketpipeline", "a.py", 1),
        _mk("ticketpipelines", "b.py", 2),
        _mk("zzz_totally_unrelated", "c.py", 3),
    ]
    groups = fs.group_items(items)
    jw_groups = [g for g in groups if g.similarity == "jaro-winkler"]
    assert len(jw_groups) == 1
    assert {i.name for i in jw_groups[0].items} == {"ticketpipeline", "ticketpipelines"}


def test_group_empty_and_short_names_skipped() -> None:
    items = [_mk("a"), _mk("b"), _mk("c")]
    # All too short (<4 chars normalized) for Jaro-Winkler pass; normalized-match
    # requires ≥2 items with same normalized name — each is unique.
    groups = fs.group_items(items)
    assert groups == []


def test_group_sorted_by_size_desc_then_alpha() -> None:
    items = [
        _mk("get_alpha", "a.py"),
        _mk("fetch_alpha", "b.py"),
        _mk("get_zulu", "c.py"),
        _mk("fetch_zulu", "d.py"),
        _mk("get_zulu_handler", "e.py"),  # third "zulu" member
    ]
    groups = fs.group_items(items)
    assert [g.normalized_name for g in groups] == ["zulu", "alpha"]
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `uv run pytest tests/scripts/test_find_similar.py -k group -v`
Expected: FAIL — `group_items` / `Group` not defined.

- [ ] **Step 3: Implement grouping**

Append to `scripts/find_similar.py`:

```python
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
```

- [ ] **Step 4: Run grouping tests, confirm pass**

Run: `uv run pytest tests/scripts/test_find_similar.py -k group -v`
Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/find_similar.py tests/scripts/test_find_similar.py
git commit -m "feat(scripts): find_similar — normalized-match + Jaro-Winkler grouping"
```

---

## Task 10: `find_similar.py` — file discovery, output, CLI (TDD where useful)

**Files:**
- Modify: `scripts/find_similar.py` (append)
- Modify: `tests/scripts/test_find_similar.py` (append)

- [ ] **Step 1: Write failing discovery + output tests**

Append to `tests/scripts/test_find_similar.py`:

```python
def test_discover_python_files(tmp_path: Path) -> None:
    # Simulate packages/*/src/... layout
    _write(tmp_path, "packages/engine/src/a2sdlc/stage.py", "def run(): ...")
    _write(tmp_path, "packages/engine/src/a2sdlc/__pycache__/x.py", "def x(): ...")
    _write(tmp_path, "packages/engine/src/a2sdlc/gen.generated.py", "def g(): ...")
    _write(tmp_path, "packages/dispatcher/src/a2sdlc_dispatcher/d.py", "def d(): ...")
    _write(tmp_path, "tests/test_x.py", "def t(): ...")  # excluded
    _write(tmp_path, "docs/x.py", "def x(): ...")  # excluded (not under packages/)

    files = sorted(p.relative_to(tmp_path).as_posix() for p in fs.discover_files(tmp_path))
    assert files == [
        "packages/dispatcher/src/a2sdlc_dispatcher/d.py",
        "packages/engine/src/a2sdlc/stage.py",
    ]


def test_render_markdown_empty() -> None:
    md = fs.render_markdown([])
    assert "No similar-name clusters found" in md


def test_render_markdown_with_groups() -> None:
    g = fs.Group(
        normalized_name="ticket",
        similarity="normalized-match",
        items=(
            fs.Item("get_ticket", "a.py", 3, "function", "() -> Ticket"),
            fs.Item("fetch_ticket_handler", "b.py", 9, "function", "() -> None"),
        ),
    )
    md = fs.render_markdown([g])
    assert "## Similar names found — 1 group, 2 items" in md
    assert "Group 1: \"ticket\"" in md
    assert "a.py:3" in md
    assert "b.py:9" in md
    assert "[function]" in md


def test_render_json_payload_shape() -> None:
    g = fs.Group(
        normalized_name="ticket",
        similarity="normalized-match",
        items=(fs.Item("a", "x.py", 1, "function", "()"),
               fs.Item("b", "y.py", 2, "function", "()")),
    )
    payload = fs.render_json_payload([g])
    assert payload["totalItems"] == 2
    assert payload["groupCount"] == 1
    assert payload["groups"][0]["normalized_name"] == "ticket"
    assert {i["name"] for i in payload["groups"][0]["items"]} == {"a", "b"}
    # Must be JSON-serializable
    json.dumps(payload)
```

- [ ] **Step 2: Run, confirm failures**

Run: `uv run pytest tests/scripts/test_find_similar.py -k "discover or render" -v`
Expected: FAIL — functions undefined.

- [ ] **Step 3: Implement discovery, rendering, and CLI**

Append to `scripts/find_similar.py`:

```python
import fnmatch
from collections.abc import Iterator

_INCLUDE_GLOB = "packages/*/src/"
_EXCLUDE_GLOBS = (
    "*/__pycache__/*",
    "*/.venv/*",
    "*/tests/*",
    "*.generated.py",
    "*/node_modules/*",
)


def _excluded(rel_path: str) -> bool:
    return any(fnmatch.fnmatch(rel_path, pat) for pat in _EXCLUDE_GLOBS)


def discover_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for pkg_src in root.glob("packages/*/src"):
        for f in pkg_src.rglob("*.py"):
            rel = f.relative_to(root).as_posix()
            if _excluded(rel):
                continue
            out.append(f)
    return sorted(out)


def render_markdown(groups: list[Group]) -> str:
    total_items = sum(len(g.items) for g in groups)
    lines: list[str] = []
    s_groups = "" if len(groups) == 1 else "s"
    s_items = "" if total_items == 1 else "s"
    lines.append(
        f"## Similar names found — {len(groups)} group{s_groups}, {total_items} item{s_items}"
    )
    lines.append("")
    for idx, g in enumerate(groups, start=1):
        lines.append(
            f'### Group {idx}: "{g.normalized_name}" ({g.similarity}, {len(g.items)})'
        )
        for it in g.items:
            lines.append(f"- **{it.name}** [{it.kind}] `{it.signature}`")
            lines.append(f"  `{it.path}:{it.line}`")
        lines.append("")
    if not groups:
        lines.append("_No similar-name clusters found._")
        lines.append("")
    return "\n".join(lines) + "\n"


def render_json_payload(groups: list[Group]) -> dict:
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "totalItems": sum(len(g.items) for g in groups),
        "groupCount": len(groups),
        "groups": [
            {
                "normalized_name": g.normalized_name,
                "similarity": g.similarity,
                "items": [asdict(it) for it in g.items],
            }
            for g in groups
        ],
    }


def _iter_items(root: Path) -> Iterator[Item]:
    for f in discover_files(root):
        yield from extract_from_file(f, root=root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="suppress markdown output")
    parser.add_argument("--markdown", action="store_true", help="suppress json output")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="project root (defaults to cwd)",
    )
    ns = parser.parse_args(argv)

    want_json = not ns.markdown or ns.json
    want_markdown = not ns.json or ns.markdown

    items = list(_iter_items(ns.root))
    groups = group_items(items)

    if want_markdown:
        print(render_markdown(groups), end="")

    if want_json:
        out = ns.root / ".similar-report.json"
        payload = render_json_payload(groups)
        out.write_text(json.dumps(payload, indent=2) + "\n")
        if want_markdown:
            print(f"\n[find-similar] Wrote {out.relative_to(ns.root)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run all find_similar tests**

Run: `uv run pytest tests/scripts/test_find_similar.py -v`
Expected: all tests pass.

- [ ] **Step 5: Smoke-test the CLI against the real repo**

Run: `uv run python scripts/find_similar.py`
Expected: prints a markdown summary + writes `.similar-report.json`. Exit code 0.

Run: `echo $?` → `0`.

- [ ] **Step 6: Commit**

```bash
git add scripts/find_similar.py tests/scripts/test_find_similar.py
git commit -m "feat(scripts): find_similar — file discovery, markdown/json output, CLI"
```

---

## Task 11: Wire `make similar`

**Files:**
- Modify: `Makefile` (new target)

- [ ] **Step 1: Add `similar` target**

Append to `/Users/iorlas/Workspaces/a2sdlc-engine/Makefile`:

```makefile
similar: ## Report similarly-named functions/classes (advisory)
	@uv run python scripts/find_similar.py
```

- [ ] **Step 2: Run and verify**

Run: `make similar`
Expected: markdown summary printed, `.similar-report.json` written, exit 0.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "feat(make): add 'make similar' advisory target for reuse-finder"
```

---

## Task 12: Full verification

**Files:** none modified — only verification.

- [ ] **Step 1: Run the full gate**

Run: `make check`
Expected: `lint` (agent-harness + jscpd + actionlint), `arch`, `test`, `coverage-diff`, `security-audit` all pass.

If `lint-jscpd` fails because existing duplication in the codebase exceeds 6%, note the reported percentage. Options (to discuss with reviewer, not resolve inside this task):
- Raise `threshold` temporarily in `.config/jscpd.json`.
- Extract the offending duplication in a follow-up.

Do NOT skip or silence jscpd to force `make check` green — the gate must be honest. If threshold needs raising, do it explicitly and mention in the commit.

- [ ] **Step 2: Run find_similar tests in isolation**

Run: `uv run pytest tests/scripts/ -v`
Expected: all tests pass.

- [ ] **Step 3: Manual check — Claude hooks**

Inspect `.claude/settings.json` and confirm the `Stop` + `SubagentStop` → `make fix` entries are in place. No runtime test possible in this plan — the hook will fire on the next turn-end.

- [ ] **Step 4: Update commit + push**

If any adjustments (e.g. jscpd threshold) were made in Step 1, commit them:

```bash
git add -p
git commit -m "chore(lint): <adjustment description>"
```

---

## Self-review checklist

**Spec coverage:**

- ✅ `package.json` + `pnpm-lock.yaml` + `.config/jscpd.json` — Task 1
- ✅ jscpd wired into `make lint` — Task 2
- ✅ jscpd in pre-commit — Task 2
- ✅ actionlint wired into `make lint` + pre-commit — Task 3
- ✅ `.claude/settings.json` Stop/SubagentStop — Task 4
- ✅ `make bootstrap` updated — Task 5
- ✅ `find_similar.py` extraction — Task 6
- ✅ normalization (with a2sdlc-specific suffix tweaks) — Task 7
- ✅ Jaro-Winkler — Task 8
- ✅ grouping (normalized-match + JW passes, sort rules) — Task 9
- ✅ discovery, markdown/json output, CLI flags, exit 0 — Task 10
- ✅ `make similar` — Task 11
- ✅ `.gitignore` updates — Task 1 (node_modules + .similar-report.json)
- ✅ `make check` full gate verification — Task 12

**No placeholders:** All steps include concrete code or concrete commands. Exception documented: Task 12 Step 1's adjustment-commit path depends on whether existing duplication trips the 6% threshold — the decision (raise threshold vs extract duplication) is explicitly routed to the reviewer rather than pre-specified, because the answer depends on repo state at execution time.

**Type consistency:** `Item`, `Group`, `ItemKind`, `normalize_name`, `jaro_winkler`, `group_items`, `extract_from_file`, `discover_files`, `render_markdown`, `render_json_payload`, `main` — used with the same signatures across Tasks 6–10.
