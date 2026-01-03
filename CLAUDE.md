# a2sdlc — Agent-to-SDLC

AI agent pipeline engine. Routes ticket board events to specialized agents (PRD, Plan, Implement, Review, CI-Assess) via Claude Code CLI. Adapters handle Jira and GitHub I/O. Agent focuses purely on code work.

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
