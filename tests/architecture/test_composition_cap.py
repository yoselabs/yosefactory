"""CLAUDE.md rule: only pipeline/dispatch.py + cli/*.py import from >=5
a2sdlc packages. Everything else stays narrowly-scoped.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).parents[2] / "packages/engine/src/a2sdlc"
# Designated composition roots: the pipeline hub + CLI subcommand
# entry points. Everything else must keep a narrow import footprint.
EXEMPT = {
    "pipeline/dispatch.py",
    "cli/dispatch.py",
    "cli/run_stage.py",
    # Local-mode composition root — wires the pipeline for `a2sdlc run`,
    # mirroring `cli/dispatch.py` for the GH path.
    "cli/run_pipeline.py",
}
CAP = 5


def _top_level_a2sdlc_packages(source: str) -> set[str]:
    tree = ast.parse(source)
    packages: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("a2sdlc.")
        ):
            parts = node.module.split(".")
            if len(parts) >= 2:
                packages.add(parts[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("a2sdlc."):
                    packages.add(alias.name.split(".")[1])
    return packages


def test_no_module_imports_from_five_or_more_packages():
    violations = []
    for py in ROOT.rglob("*.py"):
        rel = py.relative_to(ROOT).as_posix()
        if rel in EXEMPT or py.name == "__init__.py":
            continue
        pkgs = _top_level_a2sdlc_packages(py.read_text())
        if len(pkgs) >= CAP:
            violations.append((rel, sorted(pkgs)))
    assert not violations, (
        "Only dispatch + CLI may import from 5+ a2sdlc packages: "
        + "; ".join(f"{f} imports from {ps}" for f, ps in violations)
    )
