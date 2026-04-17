# Architecture Decision Records

Each ADR captures a single decision and the reasoning behind it. Living docs
(`docs/architecture.md`) describe **what** the code looks like today; ADRs record
**why** we chose that shape, so future-you can retrace reasoning without
re-litigating.

## When to add one

Write an ADR when you make a decision that:

- Constrains future choices (e.g. "no ORM", "one composition root")
- Contradicts an obvious alternative (e.g. "flat package over nested")
- Would be hard to explain from code alone

Skip ADRs for routine choices (library selection, variable names, local fixes).

## Format

Numbered, dated, status-tagged:

```
NNNN-short-slug.md
```

Each ADR has four sections: **Context** (what problem), **Decision** (what we're
doing), **Consequences** (what this costs us), **Alternatives considered**
(with one-line rejection reason each). Keep them short — under 200 lines.

## Status values

- `Proposed` — under discussion
- `Accepted` — decision in force
- `Superseded by NNNN` — replaced by a later ADR
- `Deprecated` — no longer in force, not yet replaced

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-hexagonal-lite-over-ddd.md) | Hexagonal-lite architecture (not full DDD) | Accepted |
| [0002](0002-keep-empty-init-py.md) | Keep empty `__init__.py` files | Accepted |
| [0003](0003-evaluation-not-telemetry.md) | Name the measurement package `evaluation/`, not `telemetry/` | Accepted |
| [0004](0004-enforce-architecture-with-import-linter.md) | Enforce architecture rules via `import-linter` | Accepted |
