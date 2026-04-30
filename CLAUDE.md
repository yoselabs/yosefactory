# a2sdlc — Agent-to-SDLC

AI agent pipeline engine. Routes ticket board events through stages (Spec, Implement, Review, Merge) using the Claude Agent SDK. Each stage is a self-contained module in `src/a2sdlc/stages/`. Adapters handle Jira and GitHub I/O. The agent focuses purely on code work — the engine manages orchestration, progress tracking, and post-condition routing.

## Architecture

Hexagonal-lite layout. Read `docs/architecture.md` before adding modules. Summary of the rules:

- **Layers:** `domain/` (pure types, zero I/O) ← `adapters/` ← `lifecycle/` · `assembly/` · `evaluation/` · `observability/` ← `ingress/` · `gating/` · `effects/` · `middleware/` · `composition/` ← `pipeline/` (slim composition — dispatch + runner + stage_executor). Dependency arrows point inward.
- **Folders are product concerns, not tech concerns.** `evaluation/` not `telemetry/`, `lifecycle/` not `managers/`, `pipeline/` not `core/`.
- **Extract a package the moment two sibling-suffixed files appear** (`*_lifecycle`, `*_assembly`, `*_routing`). The suffix is the package name.
- **Only `pipeline/dispatch.py` may import from 5+ other a2sdlc packages.** It's the one composition root.
- **Stays flat at root:** entry points (`cli.py`, `__main__.py`) and `config.py`. Nothing else.
- **Domain purity is non-negotiable:** `domain/` imports nothing from other a2sdlc packages. CI must fail on violation.

## Dev Commands

```bash
make lint          # agent-harness lint (runs all checks, safe anytime)
make fix           # auto-fix formatting, then lint
make test          # run tests (with coverage; skips recorded GH integration)
make test-integration        # replay recorded GH adapter cassettes (no network)
make record-integration      # re-record cassettes — needs GITHUB_TOKEN for iorlas/a2sdlc-smoke
make security-audit          # check deps + secrets in working dir (fast)
make check                   # full gate: lint + test + test-integration + coverage-diff + security-audit
make smoke-local             # end-to-end smoke against a scratch local-origin repo (opt-in via ANTHROPIC_API_KEY)
make bootstrap               # first-time setup: deps + harness config + pre-commit hooks
agent-harness security-audit-history  # deep scan git history for deleted secrets (run once)
```

## Workflow

Pre-commit hooks run `agent-harness fix` and `agent-harness lint` automatically on every commit.
Before declaring work done, always run `make check` — it's the full quality gate.
If `make coverage-diff` fails, write tests for the uncovered lines you changed.
On first setup or when onboarding a new repo, run `agent-harness security-audit-history` once to scan full git history for leaked secrets.

## GH adapter integration tier

Cassette-backed tests at `tests/integration/adapters/` catch PyGithub
auth-mode bugs that unit-test mocks miss (two such bugs shipped to main
on 2026-04-21 — see the reflect signal dated the same). Touching
`adapters/work/github.py` or `adapters/review/github.py`:

1. Run `make test-integration` — replays current cassettes, no token needed.
2. If a response shape changed or a new endpoint is called, re-record:
   ```bash
   GITHUB_TOKEN=ghs_... make record-integration   # installation token
   git add tests/integration/adapters/cassettes
   ```
3. Scrubber in `tests/integration/adapters/conftest.py` strips
   `authorization` / cookies before cassettes hit disk. Diff cassettes
   before committing — no live token should ever appear.

If `test-integration` says "no cassettes — skipping", the tier is
dormant. Seed it once with a real installation token from the smoke
repo's App and commit the cassettes.

## Never

- Never truncate lint/test output with `| tail` or `| head` — output is already optimized
- Never skip `make check` before declaring a task complete
- Never commit cassettes without diffing them first — a leaked `authorization` header is a credential disclosure
