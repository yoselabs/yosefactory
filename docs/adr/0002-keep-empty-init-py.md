# 0002 — Keep empty `__init__.py` files

- **Status:** Accepted
- **Date:** 2026-04-18

## Context

PEP 420 (2012) made `__init__.py` optional — folders without it become *namespace
packages*. Some modern Python projects delete empty `__init__.py` files as
"clutter." The question came up: should we?

Today the codebase has 8 package `__init__.py` files. **3 hold real content**
(top-level `a2sdlc/`, `adapters/`, `stages/`) and **5 are empty** (`domain/`,
`pipeline/`, `lifecycle/`, `assembly/`, `evaluation/`, `prompts/`).

PEP 420's intended use case was splitting a package across *multiple PyPI
distributions* (e.g. the `zope.*` ecosystem). Single-project use was a side effect.

## Decision

**Every package has `__init__.py`, even if empty.** Use regular packages
(PEP 328) consistently.

If an `__init__.py` later grows content, that content should be a **public API
re-export** (see `adapters/__init__.py` for the pattern) — not miscellaneous
utilities.

## Consequences

- 5 "empty" files of 0 bytes each stay in the tree. Aesthetic cost: ≤ 0.
- Tooling behaves predictably (hatchling, `import-linter`, ty, pytest-cov).
- A future `import-linter` rule can forbid empty `__init__.py` creep if desired,
  or require docstrings.
- **We accept one trade-off we cannot mitigate cheaply:** if and when
  `__init__.py` does hold re-exports, it becomes a merge-conflict hotspot for
  multi-agent parallel work. We defer re-exports until a genuinely cross-cutting
  public API emerges — we do *not* pre-emptively barrel-export everything.

## Alternatives considered

- **Delete all empty `__init__.py`.** Rejected: mixes regular and namespace
  packages in the same project, which is the configuration most prone to silent
  tooling surprises (wheel packaging, resolution priority, `__all__` handling).
- **Delete only some.** Rejected for the same reason — mixed state is worse than
  either consistent choice.
- **Convert everything to namespace packages.** Rejected: `adapters/__init__.py`
  and `stages/__init__.py` already hold registry logic; converting would require
  moving that logic elsewhere for no clear gain.
