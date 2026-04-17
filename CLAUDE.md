# a2sdlc — Agent-to-SDLC

AI agent pipeline engine. Routes ticket board events through stages (Spec, Implement, Review, Merge) using the Claude Agent SDK. Each stage is a self-contained module in `src/a2sdlc/stages/`. Adapters handle Jira and GitHub I/O. The agent focuses purely on code work — the engine manages orchestration, progress tracking, and post-condition routing.

## Architecture

Hexagonal-lite layout. Read `docs/architecture.md` before adding modules. Summary of the rules:

- **Layers:** `domain/` (pure types, zero I/O) ← `adapters/` ← `lifecycle/` · `assembly/` · `evaluation/` ← `pipeline/` (composition). Dependency arrows point inward.
- **Folders are product concerns, not tech concerns.** `evaluation/` not `telemetry/`, `lifecycle/` not `managers/`, `pipeline/` not `core/`.
- **Extract a package the moment two sibling-suffixed files appear** (`*_lifecycle`, `*_assembly`, `*_routing`). The suffix is the package name.
- **Only `pipeline/dispatch.py` may import from 5+ other a2sdlc packages.** It's the one composition root.
- **Stays flat at root:** entry points (`cli.py`, `__main__.py`) and `config.py`. Nothing else.
- **Domain purity is non-negotiable:** `domain/` imports nothing from other a2sdlc packages. CI must fail on violation.

## Dev Commands

```bash
make lint          # agent-harness lint (runs all checks, safe anytime)
make fix           # auto-fix formatting, then lint
make test          # run tests (with coverage)
make security-audit          # check deps + secrets in working dir (fast)
make check                   # full gate: lint + test + coverage-diff + security-audit
make bootstrap               # first-time setup: deps + harness config + pre-commit hooks
agent-harness security-audit-history  # deep scan git history for deleted secrets (run once)
```

## Workflow

Pre-commit hooks run `agent-harness fix` and `agent-harness lint` automatically on every commit.
Before declaring work done, always run `make check` — it's the full quality gate.
If `make coverage-diff` fails, write tests for the uncovered lines you changed.
On first setup or when onboarding a new repo, run `agent-harness security-audit-history` once to scan full git history for leaked secrets.

## Never

- Never truncate lint/test output with `| tail` or `| head` — output is already optimized
- Never skip `make check` before declaring a task complete
