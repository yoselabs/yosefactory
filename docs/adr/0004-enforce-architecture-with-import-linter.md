# 0004 — Enforce architecture rules via `import-linter`

- **Status:** Accepted
- **Date:** 2026-04-18

## Context

`docs/architecture.md` defines layering rules: domain is pure, adapters don't
import application code, sibling application packages (`lifecycle/`, `assembly/`,
`evaluation/`) don't import each other, only `pipeline/dispatch.py` is allowed a
wide import footprint.

Without enforcement, these rules decay the moment two agents (or humans) forget
them. The refactor that introduced the layout even turned up two existing
violations once `import-linter` was run (`RunResult` living in `pipeline/` but
referenced by the `adapters/` port; `config.py` importing `stages` for default
merging).

## Decision

Adopt **`import-linter`** as a CI-enforced check. Rules live in
`pyproject.toml` under `[tool.importlinter]`. Run via `make arch`, which `make
check` invokes.

Start with the rules that reflect the layering table in `docs/architecture.md §2`:

1. Domain purity — non-negotiable.
2. Adapters do not import application packages.
3. Application packages (`lifecycle/`, `assembly/`, `evaluation/`) do not import
   `pipeline/` or `cli/`.
4. Sibling application packages do not import each other.

Legitimate exceptions (e.g. `config.py` lazy-imports `stages` for default
merging) are declared inline via `ignore_imports`, with a comment pointing to
the architecture doc section that justifies them.

## Consequences

- Architecture rules become **contract, not documentation**. A PR that breaks
  layering fails CI rather than drifting silently.
- Adding rules is cheap — one TOML block per contract.
- New agents/contributors get immediate, specific feedback ("X not allowed to
  import Y") instead of vague "this doesn't look right" in review.
- Low conflict surface for multi-agent work: `pyproject.toml` changes rarely
  (only when rules change, not when features are added).
- The first run revealed genuine layering leaks (see Context). The tool pays
  for itself on installation.

## Alternatives considered

- **Rely on review / docs only.** Rejected: humans and agents both miss subtle
  violations. The cost of one undetected leak (tangled boundaries to untangle
  later) vastly exceeds the tool's maintenance cost.
- **Custom `ast`-based linter.** Rejected: `import-linter` solves this well and
  is maintained; rolling our own is not worth the engineering.
- **`ruff`'s `TID` rules.** Rejected: `ruff` catches specific forbidden imports
  per-file but lacks package-level contracts (transitive chains, sibling rules).
  Complementary, not a replacement.

## Related

- `docs/architecture.md §8 (Enforcement)` — describes how the rules are
  enforced and the threshold for adding new ones.
