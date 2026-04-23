---
title: "P8 — Lock the shape"
type: spec
status: Executed
owner: "@iorlas"
created: 2026-04-23
updated: 2026-04-23
rfc: "../../rfcs/0001-v1-scope.md"
author:
  human: "@iorlas"
  agent: "claude-opus-4-7 (V1.0 execution session 2026-04-23)"
---

# P8 — Lock the shape

## Goal

Encode the layering rules from `docs/architecture.md` §2 as
`import-linter` contracts plus an architecture pytest test. Promote
two CLAUDE.md conventions ("dependency arrows point inward," "only
`pipeline/dispatch.py` imports from 5+ a2sdlc packages") from
aspirational comment to CI-enforced rule. Failures surface at
`make check` / pre-commit.

V1.0 success criterion: a fresh branch that introduces a boundary
violation (e.g. `domain/` importing from `pipeline/`) fails lint
before reaching code review.

Final V1.0 migration-phase spec. Appetite: **1 day.**

## Non-goals

- **No L6 smoke in `make check`.** L6 smoke is valuable but belongs
  in a dedicated CI job — `make check` must stay fast for the TDD
  loop. Post-P8 1-commit add if wanted.
- **No contract changes to the layering rules themselves.** P8
  encodes what P7 established — no "while we're here" reshape.
- **No architecture-test framework adoption** (`pytest-arch-check`
  et al.). A single hand-rolled pytest for the composition-root cap
  is enough.

## Layer stack

```
Layer 0  domain/                                              # pure types
Layer 1  config                                               # config.py — mostly leaf
Layer 2  adapters/                                            # ports
Layer 3  lifecycle/  observability/  evaluation/  assembly/   # peer tier A
Layer 4  ingress/  gating/  effects/  middleware/  stages/    # peer tier B
Layer 5  composition/                                         # profile + builders
Layer 6  pipeline/                                            # dispatch hub
Layer 7  cli/                                                 # entry points
```

Each layer may import from any lower-numbered layer. Peer tier A
(lifecycle/assembly/evaluation/observability) has a mutual-isolation
rule: no imports between them. Peer tier B allows intra-tier imports
on the inward-only principle baked into the `layered` contract.

## Contract file

One `.importlinter` at repo root (fallback to `[tool.importlinter]`
in `pyproject.toml` if the harness prefers).

```ini
[importlinter]
root_package = a2sdlc

# ── Main layered contract — inward-only deps ─────────────────────────
[importlinter:contract:layers]
name = Hexagonal layers (a2sdlc)
type = layers
layers =
    a2sdlc.cli
    a2sdlc.pipeline
    a2sdlc.composition
    a2sdlc.ingress | a2sdlc.gating | a2sdlc.effects | a2sdlc.middleware | a2sdlc.stages
    a2sdlc.lifecycle | a2sdlc.observability | a2sdlc.evaluation | a2sdlc.assembly
    a2sdlc.adapters
    a2sdlc.config
    a2sdlc.domain

# ── Peer-tier-A mutual isolation ─────────────────────────────────────
[importlinter:contract:peer-tier-A-isolated]
name = lifecycle/assembly/evaluation/observability don't import from each other
type = independence
modules =
    a2sdlc.lifecycle
    a2sdlc.assembly
    a2sdlc.evaluation
    a2sdlc.observability

# ── Domain purity (non-negotiable) ───────────────────────────────────
[importlinter:contract:domain-purity]
name = domain imports nothing from a2sdlc
type = forbidden
source_modules = a2sdlc.domain
forbidden_modules =
    a2sdlc.cli
    a2sdlc.pipeline
    a2sdlc.composition
    a2sdlc.ingress
    a2sdlc.gating
    a2sdlc.effects
    a2sdlc.middleware
    a2sdlc.stages
    a2sdlc.lifecycle
    a2sdlc.observability
    a2sdlc.evaluation
    a2sdlc.assembly
    a2sdlc.adapters
```

## Composition-root cap test

`tests/architecture/test_composition_cap.py`:

```python
"""CLAUDE.md rule: only pipeline/dispatch.py + cli/*.py import from ≥5
a2sdlc packages. Everything else stays narrowly-scoped.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).parents[2] / "packages/engine/src/a2sdlc"
EXEMPT = {"pipeline/dispatch.py", "cli/dispatch.py", "cli/run_stage.py"}
CAP = 5


def _top_level_a2sdlc_packages(source: str) -> set[str]:
    tree = ast.parse(source)
    packages: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("a2sdlc."):
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
```

`__init__.py` exempt — package re-exports legitimately re-import from
peers. CLI files + `pipeline/dispatch.py` exempt — they're the
designated composition roots.

## Plan

Each step = one commit. 6 steps.

1. **Discovery + install.** Grep for existing import-linter config
   (the P7-era `a2sdlc.assembly is not allowed…` error suggests
   something already enforces a contract). If it exists, step 2
   edits it. If not, add `import-linter` to dev dependencies +
   confirm `lint-imports` runs.

2. **Write the contract file.** Three contracts: `layers`,
   `independence` (peer tier A), `forbidden` (domain purity). Run
   `lint-imports`; confirm all three pass against the current
   codebase. If any cross-peer import is legitimate but the
   contract rejects it, either refactor the import or add an
   `ignore_imports` whitelist (one commit per decision).

3. **Wire into `make check`.** Confirm `agent-harness lint` already
   invokes `lint-imports`, or add a dedicated `make arch` target
   that `make check` chains.

4. **Add composition-root cap test.** `tests/architecture/test_composition_cap.py`
   per §Composition-root cap test. Run; must pass — dispatch + both
   CLI files are the only expected ≥5 offenders.

5. **Mutation check.** Throwaway commit: add `import a2sdlc.pipeline`
   to `domain/models.py`. Confirm `make check` fails loudly on both
   the layers contract AND (if CLI files added) the cap test.
   Revert immediately. Document the mutation-test outcome in the
   step 6 commit message.

6. **Spec status → Executed.** Update RFC §Quality gates if needed
   to reference the shipped contract file path.

## File-level changes

| File | Change |
|---|---|
| `.importlinter` or `pyproject.toml` | **New** (or modified) — 3 contracts |
| `packages/engine/pyproject.toml` | Add `import-linter` to dev deps (if not already present) |
| `tests/architecture/__init__.py` | **New** — empty |
| `tests/architecture/test_composition_cap.py` | **New** — the cap test |
| `Makefile` | Modified — add `arch` target if missing + wire to `check` |

## Test strategy

- **L1 — composition-cap test.** Self-asserting against the current
  tree.
- **L3 (conceptually) — import-linter at `make check`.** Catches
  boundary violations at commit time.
- **Manual mutation check (step 5).** Validates both the contracts
  and the cap test bite.

## Security considerations

None — pure tooling / lint addition.

## Rollout

Ships on main one step at a time. Highest-risk step is **step 2** —
the first contract run might surface legitimate cross-peer imports
that P7 didn't anticipate. Mitigation: each whitelist decision
(`ignore_imports` line) gets its own commit with justification.

## Backout

Each step revertible in isolation. Step 2's contract file can be
deleted; step 4's test file can be deleted. Neither changes
production code.

## Links

- RFC: [../../rfcs/0001-v1-scope.md](../../rfcs/0001-v1-scope.md)
- Architecture vision §7.1 (the target the contract locks down)
- `docs/architecture.md` §2 (the rules we're encoding)
- P7 spec (prerequisite): `2026-04-23-p7-rename-relocate-design.md`
