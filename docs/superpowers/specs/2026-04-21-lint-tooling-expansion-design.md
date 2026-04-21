# Lint Tooling Expansion — Design

**Date:** 2026-04-21
**Source:** concepts adapted from `agentic-web-stack` (TS monorepo)
**Scope:** add jscpd (copy-paste detection), actionlint (GitHub Actions), a Python port of `find-similar` (duplicate/similar symbol detector), and wire `make fix` into Claude Code Stop/SubagentStop hooks.

## Motivation

`agentic-web-stack` runs ~30 lint tasks in parallel through Turbo. Most are JS-locked or app-specific, but a handful are language-agnostic or conceptually portable and fill real gaps in a2sdlc-engine's current lint surface:

- **Duplication detection** — a2sdlc has no copy-paste lint today. Stages are structurally similar, easy to drift into copy-paste.
- **Duplicate/similar symbol names** — helps the agent (and humans) find existing code to reuse instead of recreating it. Directly relevant to a2sdlc's own mission.
- **GitHub Actions lint** — 3 workflows exist (`run-native.yml`, `run-split.yml`, `unblock-next.yml`), zero lint coverage.
- **Auto-fix on agent turn-end** — `make fix` already exists but runs only manually. Making it fire on Stop / SubagentStop keeps the working tree formatted without the user asking.

Checks *not* migrated (out of scope, with rationale):

- biome, tsc, knip, sherif, publint, prisma, depcruise, no-barrel, trpc-patterns, server-bind, domain-names, test-infra-integrity, feature-emails, test-siblings, stories-siblings, adrs, state-machines, pitch-coverage, scoped-landmarks, perspective-boundary — JS-locked or app-specific to `agentic-web-stack`.
- secretlint — already covered by `agent-harness security-audit`.
- dependency-cruiser — already covered by `importlinter` contracts in `pyproject.toml`.
- hadolint, markdownlint, link-check, cspell, shellcheck — intentionally deferred (low signal:effort or no target files).

## 1. jscpd

Detects copy-paste blocks across the Python codebase. Hard gate with a tolerance percentage, matching `agentic-web-stack`'s model.

### Files

- **`package.json`** (new, repo root):
  ```json
  {
    "name": "a2sdlc-lint-tooling",
    "private": true,
    "packageManager": "pnpm@9",
    "scripts": {
      "lint:jscpd": "jscpd --config .config/jscpd.json",
      "lint:actions": "actionlint"
    },
    "devDependencies": {
      "jscpd": "^4.0.9"
    }
  }
  ```
  Rationale for Node-in-a-Python-repo: isolating to one `package.json` at root + `pnpm-lock.yaml` keeps the footprint minimal. `node_modules/` is gitignored. Only developers who want to run jscpd locally need pnpm; CI runs `pnpm install` as part of the check step.

- **`pnpm-lock.yaml`** — checked in.

- **`.config/jscpd.json`** (new):
  ```json
  {
    "$schema": "https://unpkg.com/jscpd@latest/schemas/jscpd.json",
    "threshold": 6,
    "reporters": ["console"],
    "absolute": false,
    "gitignore": true,
    "format": ["python"],
    "min-tokens": 50,
    "min-lines": 8,
    "ignore": [
      "**/.venv/**",
      "**/node_modules/**",
      "**/__pycache__/**",
      "**/tests/**",
      "**/*.generated.py",
      "**/coverage.xml",
      "docs/**",
      "skills/**",
      ".claude/**",
      ".similar-report.json"
    ]
  }
  ```
  `threshold: 6` = fail if >6% of code is duplicated. Starts loose; can be ratcheted down over time.

- **`.gitignore`** — add: `node_modules/`, `.similar-report.json`.

### Makefile wiring

```makefile
lint: agent-harness-lint lint-jscpd lint-actions

agent-harness-lint:
	agent-harness lint

lint-jscpd:
	pnpm lint:jscpd

lint-actions:
	pnpm lint:actions
```

(The existing single-line `lint:` target is replaced with the aggregated form above.)

### Pre-commit hook

Per `CLAUDE.md`, the pre-commit hook currently invokes `agent-harness lint` directly — so jscpd added only to the `make lint` target will NOT run under pre-commit. To keep pre-commit coverage aligned with `make lint`:

- Add a pre-commit hook entry that runs `pnpm lint:jscpd` (after `agent-harness lint`).
- Same for `actionlint` — but scoped to `.github/workflows/**` file changes.

Hook config file location (e.g. `.pre-commit-config.yaml`) will be determined during implementation by reading the current pre-commit setup — not yet inspected for this spec.

### Bootstrap

`make bootstrap` gains:

```makefile
bootstrap:
	uv sync
	agent-harness init --apply
	@command -v pnpm >/dev/null && pnpm install || echo "⚠  pnpm not found — install via 'brew install pnpm' to enable jscpd/actionlint"
	@command -v actionlint >/dev/null || echo "⚠  actionlint not found — install via 'brew install actionlint'"
	...
```

Soft warnings, not hard failures — the rest of the toolchain still works without them; only `make lint` / `make check` will fail until they're installed.

## 2. actionlint

Lints `.github/workflows/*.yml`. External Go binary, invoked via the pnpm script above (acts only as a thin command wrapper — no npm package dependency).

- **Install**: `brew install actionlint` on macOS. CI uses `rhysd/actionlint` GitHub Action.
- **Config**: none initially — default rules.
- **Scope**: `.github/workflows/*.yml` (actionlint auto-detects).

## 3. `make fix` on Claude Code Stop / SubagentStop

### Hook config

Add to `.claude/settings.json` (or `.claude/settings.local.json` for per-user):

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [{ "type": "command", "command": "make fix" }]
      }
    ],
    "SubagentStop": [
      {
        "matcher": "",
        "hooks": [{ "type": "command", "command": "make fix" }]
      }
    ]
  }
}
```

### Keeping `make fix` fast

`make fix` today runs `agent-harness fix` — formatters + auto-fixes, no tests, no jscpd, no actionlint. Stays that way. jscpd and actionlint have no auto-fix surface; they only appear in `make lint` / `make check`.

## 4. `find-similar` — Python port

Python port of `agentic-web-stack/scripts/dev/find-similar.ts`. Helps the agent find reusable code by grouping symbols with identical normalized names or high Jaro-Winkler similarity.

**Advisory only — always exits 0. Never part of `make lint` or `make check`.** Surfaced via a dedicated `make similar` target, intended to be run on demand (by humans, or by agents during planning / reuse-search).

### Location

`scripts/find_similar.py` — pure Python stdlib, no new dependencies. Invoked via `uv run python scripts/find_similar.py`.

### Scope

Walks `packages/*/src/a2sdlc/**/*.py`. Excludes:
- `tests/`
- `__pycache__/`
- `**/*.generated.py`
- `.venv/`

### Extraction

Uses `ast` from stdlib. For each file, extracts **top-level** (module-scope) definitions where the name does not start with `_`:

| Kind       | What it matches                                                        |
|------------|------------------------------------------------------------------------|
| `function` | `def foo(...)` / `async def foo(...)`                                  |
| `class`    | `class Foo: ...`                                                       |
| `type`     | PEP 695 `type X = ...` and `X: TypeAlias = ...` annotated assignments  |

Nested definitions (methods inside classes, inner functions) are **not** extracted — they rarely participate in reuse search and would flood the output.

### Signatures

Best-effort reconstruction from AST:

- **Functions**: `(param: Type, ...) -> ReturnType`, rendered from `ast.unparse` of annotations. Unannotated params appear without a type. Async functions prefixed with `async `.
- **Classes**: `class with N methods` (direct `def`/`async def` children).
- **Types**: the RHS expression, truncated at 80 chars.

### Normalization

Direct port of the TS logic, tuned for Python idioms:

- Split camelCase / PascalCase / snake_case into lowercase words.
- Strip leading prefixes (greedy while matching): `get, set, create, make, build, fetch, load, update, delete, remove, handle, parse, format, ensure, is, has, to, from, run, do`.
- Strip trailing suffixes: `handler, service, factory, provider, context, config, schema, result, response, request, input, output, options, stage, adapter`.
- Differences from TS version: drops `use, component, hook, props` (React-specific); adds `stage, adapter` (a2sdlc-specific domain vocabulary).
- Fallback: if stripping empties the name, use the original word list.

### Grouping

Identical algorithm to the TS version:

1. **Pass 1 — normalized-match**: items with identical normalized names form a group, labelled `normalized-match`.
2. **Pass 2 — Jaro-Winkler**: over singleton normalized names (length ≥ 4), cluster pairs with Jaro-Winkler ≥ 0.9. Labelled `jaro-winkler`.
3. Sort groups by size desc, then alphabetically; sort items within a group by path then line.

Jaro-Winkler implemented inline (~40 lines, no dependency).

### Output

- **Stdout**: Markdown summary — `## Similar names found — N groups, M items` + per-group breakdown with kind, signature, and `path:line`.
- **File**: `.similar-report.json` at repo root (gitignored) — `{ generatedAt, totalItems, groupCount, groups }`.
- **Flags**: `--json` / `--markdown` to suppress the other format. Default: both.
- **Exit code**: always 0.

### Makefile

```makefile
similar: ## Report similarly-named functions/classes (advisory)
	@uv run python scripts/find_similar.py
```

## Gates summary

| Target              | Runs                                                   | Blocks? |
|---------------------|--------------------------------------------------------|---------|
| `make lint`         | agent-harness lint + jscpd + actionlint                | Yes     |
| `make fix`          | agent-harness fix                                      | N/A (fixer) |
| `make check`        | lint + arch + test + coverage-diff + security-audit    | Yes     |
| `make similar`      | find_similar.py                                        | Never (advisory) |
| Pre-commit hook     | agent-harness lint + jscpd (+ actionlint if workflows touched) | Yes |
| Claude Stop hook    | make fix                                               | No (fixer) |
| Claude SubagentStop | make fix                                               | No (fixer) |

## Out of scope

- Ratcheting the jscpd `threshold` below 6 (follow-up after initial report).
- Expanding jscpd `format` beyond `python` (e.g. add `yaml` for deploy configs).
- Migrating markdownlint, link-check, cspell, shellcheck, hadolint (deferred).
- A `no-cwd` custom rule for Python — deferred until there's evidence it's needed.
- Any mechanism to make `agent-harness` itself aware of jscpd / actionlint as plugins — for now they sit alongside via Makefile composition.

## Open items deferred to implementation

- Exact path / format of the pre-commit config (to be read and amended in-place rather than specified here).
- Whether `SubagentStop` fires too frequently to be useful in practice — revisit if `make fix` becomes a noticeable drag.
