# a2sdlc Architecture

This document defines the package layout and the rules that keep it honest.
It is load-bearing: every new module lands somewhere because of a rule below, not by default.

## 1. Shape — Hexagonal-lite

The codebase follows **Ports & Adapters (Hexagonal)** with a two-layer domain/application split.
We deliberately skip full DDD (aggregates, bounded contexts, repositories) — it's ceremony for a
domain this small.

```
src/a2sdlc/
├── cli.py, __main__.py          # entry points — root only
│
├── domain/                      # pure types, zero I/O, zero framework imports
│   ├── models.py                # StageName, StageStatus, TicketState, GateConfig, ...
│   ├── handover.py              # parse/format handover comments
│   ├── directives.py            # parse [a2sdlc ...] directives
│   └── exceptions.py            # typed pipeline errors
│
├── pipeline/                    # application layer — orchestration
│   ├── dispatch.py              # composition root (the hub)
│   ├── stage_executor.py        # run a single stage
│   ├── runner.py                # Claude Agent SDK wrapper
│   ├── feedback_routing.py      # map feedback event → target stage
│   └── context_assembly.py      # build agent context from handover + feedback
│
├── lifecycle/                   # "manage X over time"
│   ├── comment.py               # one-comment-per-stage-run lifecycle
│   ├── pr.py                    # draft PR create/update/merge-gate
│   └── state.py                 # TicketState read/write, idempotency
│
├── assembly/                    # build agent inputs from files
│   └── prompt.py                # load + concatenate stage prompt files
│
├── evaluation/                  # measure what happened (first-class concern)
│   ├── progress.py              # live run tracking + formatting
│   └── stats.py                 # cost/tokens/duration accumulator
│                                # (future: eval harness, scorers, run comparison)
│
├── config.py                    # stays flat — small, stable, imported everywhere
│
├── adapters/                    # ports & adapters (platform I/O)
│   ├── protocols.py             # ports: WorkAdapter, ReviewAdapter, GitAdapter, StageRunner
│   ├── work.py, review.py, git.py, github.py, retry.py
│
├── stages/                      # stage definitions (data, not behavior)
├── prompts/                     # prompt files (package resources)
└── hooks/                       # runtime hooks
```

## 2. Layering rules

| Package | Can import from |
|---|---|
| `domain/` | **nothing** inside a2sdlc. Third-party types only (Pydantic, stdlib). |
| `adapters/` | `domain/`, `config.py`. Never from `pipeline/`, `lifecycle/`, `assembly/`, `evaluation/`. |
| `lifecycle/`, `assembly/`, `evaluation/` | `domain/`, `config.py`, `adapters/`. Not from each other. Not from `pipeline/`. |
| `pipeline/` | everything else. This is the composition layer. |
| `cli.py` | `pipeline/`, `config.py`, `domain/`. |
| `stages/` | `domain/`, `config.py`. Stage definitions are data, not orchestration. |

**Invariant:** dependency arrows point inward (`adapters` → `domain`), never outward.
`domain/` has zero imports from the rest of a2sdlc — this is non-negotiable.

## 3. Naming rule — folders name **product concerns**, not technical concerns

| Good | Bad |
|---|---|
| `evaluation/` | `telemetry/`, `metrics/` |
| `lifecycle/` | `managers/`, `services/` |
| `pipeline/` | `core/`, `engine/`, `utils/` |
| `assembly/` | `builders/`, `factories/` |

**Test:** a new reader should be able to guess what lives in a folder from the product's vocabulary,
not from CS jargon. If the name could apply to any codebase, rename it.

## 4. Extraction rule — promote latent packages early

**The moment two files share a suffix (`*_lifecycle`, `*_assembly`, `*_routing`, `*_manager`),
extract the package.** The suffix *is* the package name.

Don't wait for five files. Two sibling-suffixed files is the trigger. Waiting produces:
- files that "could" belong together but aren't, so no one enforces the grouping
- `dispatch.py`-style hubs that keep growing because adding to the hub is easier than promoting

When extracting, use `git mv` to preserve history. Rename `comment_lifecycle.py` → `lifecycle/comment.py`
(the suffix moves into the folder name; the file becomes the noun).

## 5. Composition root — one module allowed to import broadly

**`pipeline/dispatch.py` is the only module permitted to import from five or more other a2sdlc
packages.** Everything else must stay narrow.

Any other module that grows that import footprint is a smell: it's becoming an implicit hub.
Either split its responsibilities or promote it to a deliberate composition point.

## 6. What stays flat

Small, stable, universally-imported modules stay at `src/a2sdlc/` root:
- `cli.py`, `__main__.py`, `__init__.py` — entry points
- `config.py` — configuration loading (imported by almost everything)

Everything else earns its way into a package via the rules above.

## 7. Enforcement

- **Lint:** `import-linter` config in `pyproject.toml` enforces the layering table in §2.
  Domain purity (`domain/` imports nothing from other a2sdlc packages) is the critical rule
  — CI must fail on violation.
- **Review heuristic:** if a PR adds a file to `src/a2sdlc/` root that isn't in the "what stays flat"
  list, the reviewer asks "what package does this belong to?" If the answer is "none yet," the PR
  creates that package.
- **Threshold check:** if any package (including the root) exceeds ~15 top-level files, split it
  along product-concern lines before adding a sixteenth.

## 8. When to reconsider this shape

- **Feature-slicing becomes warranted** when 3+ independent feature areas share no code. Example:
  a parallel "release notes" pipeline that doesn't touch `dispatch.py`. Then: `features/release_notes/`,
  `features/bug_triage/`, each self-contained. Not applicable today — the pipeline is one feature
  and stages are its variants.
- **Full DDD** becomes warranted when the domain has 3+ bounded contexts with divergent vocabularies.
  Not applicable today — the domain is one pipeline.

Until those triggers fire, this shape holds.
