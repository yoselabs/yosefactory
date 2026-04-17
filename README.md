# a2sdlc — Agent-to-SDLC

AI agent pipeline engine. Routes ticket-board events through autonomous stages
(Spec · Implement · Review · Merge · Deploy) using the Claude Agent SDK.

The engine manages orchestration, progress tracking, handover routing, and
evaluation. Agent systems (BMAD, Superpowers, SpecKit, raw Claude SDK, custom
prompts) plug in as **stage runners** — swappable without changing the pipeline.

## Quick start

```bash
make bootstrap          # install deps, harness config, git hooks
make check              # full quality gate: lint + arch + tests + coverage-diff + security-audit
```

See `Makefile` for the full command surface.

## Docs

| Doc | Purpose |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | **Start here.** Package layout, layering rules, naming conventions, enforcement. Read before adding modules. |
| [`docs/adr/`](docs/adr/) | Architecture Decision Records — *why* we chose the shape we did. |
| [`docs/ai-sdlc-overview.pdf`](docs/ai-sdlc-overview.pdf) | Pipeline architecture for external audiences. |
| [`docs/a2sdlc-positioning.pdf`](docs/a2sdlc-positioning.pdf) | Positioning vs BMAD / SpecKit / Superpowers. |
| [`CLAUDE.md`](CLAUDE.md) | Project instructions for AI agents working on this codebase. |

## Layout at a glance

```
src/a2sdlc/
├── domain/        pure types, no I/O
├── pipeline/      orchestration (dispatch, stage_executor, runner, ...)
├── lifecycle/     manage ticket comments, PRs, state across runs
├── assembly/      build agent inputs from files
├── evaluation/    measure run outcomes (progress, stats, future eval harness)
├── adapters/      ports + concrete platform I/O (Jira, GitHub, Git)
├── stages/        stage definitions (data, not orchestration)
├── prompts/       prompt package resources
├── hooks/         runtime hooks
├── config.py      configuration loader (glue; imported broadly)
└── cli.py         entry point
```

Layering rules are enforced by `import-linter` via `make arch` (part of
`make check`). See `docs/architecture.md §2` for the full layering table.

## Status

Early development. Core pipeline runs end-to-end; stages Spec and Implement
are production-quality; Review · Merge · Deploy are optional/phased.
