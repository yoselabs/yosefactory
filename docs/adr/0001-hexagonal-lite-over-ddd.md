# 0001 — Hexagonal-lite architecture (not full DDD)

- **Status:** Accepted
- **Date:** 2026-04-18

## Context

The codebase was bootstrapped with a flat `src/a2sdlc/` layout — 18 modules
accumulated at the package root. Latent groupings emerged (three `*_lifecycle.py`
files, two `*_assembly.py` files, a telemetry-ish cluster) but were never
extracted. Navigation cost was approaching the threshold where "where does X live?"
takes more than a second.

We considered three architectural shapes:

1. **Stay flat** — defer until file count crosses ~25.
2. **Full DDD** — bounded contexts, aggregates, repositories, domain events.
3. **Hexagonal-lite** — Ports & Adapters with a two-layer domain/application split.

## Decision

Adopt **Hexagonal-lite** as the target shape. See `docs/architecture.md` for the
concrete layout and the layering table.

Core rules:

- `domain/` — pure types, zero I/O, no framework imports.
- `adapters/` — ports (Protocols) + concrete per-platform implementations.
- Application packages named after **product concerns** (`pipeline/`,
  `lifecycle/`, `assembly/`, `evaluation/`), not tech concerns (no `core/`,
  `utils/`, `services/`, `managers/`).
- One composition root: `pipeline/dispatch.py`. Only it may import from 5+
  other packages.

## Consequences

- Every new module lands in a named package because of a rule, not by default.
- Layering is mechanically enforceable via `import-linter` (see 0004).
- The refactor tax is paid once now instead of repeatedly during organic growth.
- DDD's strategic patterns (contexts, aggregates) remain available if future
  complexity warrants them — see 0001 §Alternatives.

## Alternatives considered

- **Stay flat.** Rejected: 18 files at root already produces latent-grouping
  smell; deferring compounds the cost.
- **Full DDD.** Rejected: the domain has one bounded context (the pipeline),
  not three+. Aggregates/repositories would be ceremony for small data shapes.
  Reconsider if the system grows to multiple bounded contexts with divergent
  vocabularies.
- **Feature-slicing (`features/release_notes/`, `features/bug_triage/`).**
  Rejected: the pipeline is one feature and stages are its variants — no
  independent feature areas to slice. Reconsider when 3+ feature areas share no
  code.
