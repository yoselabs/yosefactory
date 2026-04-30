# a2sdlc Architecture

This document defines the package layout and the rules that keep it honest.
It is load-bearing: every new module lands somewhere because of a rule below, not by default.

## 1. Shape — Hexagonal-lite

The codebase follows **Ports & Adapters (Hexagonal)** with a two-layer domain/application split.
We deliberately skip full DDD (aggregates, bounded contexts, repositories) — it's ceremony for a
domain this small.

```
src/a2sdlc/
├── cli/, __main__.py            # entry points — root only
│   └── cli/main.py              # top-level dispatcher (routes subcommands)
│   └── cli/dispatch.py          # ``a2sdlc dispatch`` — GitHub pipeline entry
│   └── cli/run_stage.py         # ``a2sdlc run-stage`` — local stage runner
│
├── domain/                      # pure types, zero I/O, zero framework imports
│   ├── models.py                # StageName, StageStatus, TicketState, GateConfig, ...
│   ├── handover.py              # parse/format handover comments
│   ├── directives.py            # parse [a2sdlc ...] directives
│   ├── effects.py               # Effect ADT (side-effect descriptors)
│   ├── exceptions.py            # typed pipeline errors
│   ├── pipeline_event.py        # PipelineEvent — external trigger shape
│   ├── run_context.py           # RunContext — per-run ambient state
│   ├── run_intent.py            # RunIntent — resolved per-run routing
│   ├── run_result.py            # DispatchResult — stage execution result
│   ├── progress.py              # events + Subscriber Protocol + ProgressState bus
│   ├── stage_outcome.py         # StageOutcome — handler return shape
│   └── stats.py                 # StageRunStats — cost/tokens/duration accumulator
│
├── ingress/                     # event parsing + intent resolution (P7)
│   ├── __init__.py              # parse_event, resolve_intent, resolve_routing
│   ├── context.py               # assemble_context, pick_handover
│   └── feedback_routing.py      # map feedback event → target stage
│
├── gating/                      # pre-stage admission checks (P7)
│   ├── __init__.py              # check, check_ticket_active, check_duplicate_run_id
│   └── breakers.py              # review-cycles + cost-ceiling breakers
│
├── effects/                     # Effect interpreter + outcome translators (P7)
│   ├── apply.py                 # interpreter — Effect list → adapter calls
│   └── stage_finish.py          # outcome_to_dispatch_result + pause-reason helpers
│
├── middleware/                  # cross-cutting onion (P7)
│   ├── __init__.py              # StageAttempt / Middleware type aliases
│   ├── idempotency.py           # with_idempotency
│   └── telemetry.py             # with_telemetry (MLflow + progress envelope)
│
├── composition/                 # profile + adapter/subscriber builders (P7)
│   └── __init__.py              # CompositionProfile, resolve_*, validate_*, build_*
│
├── observability/               # progress rendering + wire setup (P7)
│   ├── progress_format.py       # pure format/extract helpers on progress data
│   └── wire.py                  # build_progress_state
│
├── pipeline/                    # composition-plus-agent-runner residuals
│   ├── dispatch.py              # composition root (the hub) — ~125 LOC post-P7
│   ├── stage_executor.py        # run a single stage
│   └── runner.py                # Claude Agent SDK wrapper
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
│   ├── telemetry.py             # Telemetry Protocol + MLflow impl
│   ├── tracked_run.py           # dispatch-fn wrapper that feeds telemetry
│   └── quality_gate.py          # post-implement make-check wrapper
│
├── runtime/                     # local-mode process primitives (stdlib-only)
│   ├── branch.py                # run-branch name generation + parser, input-hash
│   ├── dirty_tree.py            # working-tree cleanliness + protected-base guards
│   ├── env_check.py             # REQUIRED_ENV aggregator + fail-fast formatter
│   ├── isolation.py             # agent-isolation builder (pin SDK env/options)
│   ├── lockfile.py              # exclusive PID lockfile + signal-handler cleanup
│   └── state_migration.py       # lazy v0 → v1 state.json migrator
│
├── config.py                    # stays flat — small, stable, imported everywhere
│
├── adapters/                    # ports & adapters (platform I/O) — kind-first layout
│   ├── work/                    # WorkAdapter Protocol + github, local_file impls
│   ├── review/                  # ReviewAdapter Protocol + github, local_noop impls
│   ├── git/                     # GitAdapter Protocol + local, local_branch impls
│   ├── runner/                  # StageRunner Protocol (impl in pipeline/runner.py)
│   ├── subscriber/              # Subscriber impls (Protocol in domain/progress.py)
│   ├── factory.py               # name → adapter factory
│   └── retry.py                 # tenacity retry wrapper
│
├── stages/                      # stage definitions (data, not behavior)
└── prompts/                     # prompt files (package resources)
```

## 2. Layering rules

| Package | Can import from |
|---|---|
| `domain/` | **nothing** inside a2sdlc. Third-party types only (Pydantic, stdlib). |
| `adapters/` | `domain/`, `config.py`. Never from `pipeline/`, `lifecycle/`, `assembly/`, `evaluation/`, `ingress/`, `gating/`, `effects/`, `middleware/`, `composition/`, `observability/`. |
| `lifecycle/`, `assembly/`, `evaluation/`, `observability/` | `domain/`, `config.py`, `adapters/`. Not from each other. Not from `pipeline/`. |
| `runtime/` | **stdlib only.** No imports from other a2sdlc packages (not even `domain/`). Local-mode process primitives — branch naming, lockfile, dirty-tree guards, env-check, agent isolation, state migration. Imported by `cli/run.py` and (for isolation) `pipeline/runner.py`. |
| `ingress/`, `gating/`, `effects/`, `middleware/` | `domain/`, `config.py`, `adapters/`, `lifecycle/`. Not from `pipeline/`. Middleware may also import `gating/` (idempotency calls `gating.check_duplicate_run_id`). |
| `composition/` | `domain/`, `config.py`, `adapters/`, `observability/`. Not from `pipeline/`. |
| `pipeline/` | everything else. This is the composition layer. |
| `cli/` | `pipeline/`, `composition/`, `observability/`, `config.py`, `domain/`, `adapters/` (one composition point per subcommand). |
| `stages/` | `domain/`, `config.py`. Stage definitions are data, not orchestration. |

**Invariant:** dependency arrows point inward (`adapters` → `domain`), never outward.
`domain/` has zero imports from the rest of a2sdlc — this is non-negotiable.

### Local-mode CLI seam

`a2sdlc run` (the local-mode CLI added with the workflow-primitives spec)
**bypasses the GH-event ingress/dispatch chain** and drives stages directly
via `pipeline.stage_executor.StageExecutor.run`, with per-stage commit/push
and `max_review_cycles` enforcement handled inline in `cli/run_pipeline.py`.
This is a deliberate, temporary architectural seam: the GH path retains the
full `ingress → gating → effects → middleware → dispatch` flow, while local
mode short-circuits it because there is no PipelineEvent to parse and no
ticket lifecycle to manage. Future ecosystems (`github`, `jira-github`)
will continue to use the existing dispatch path. Re-unifying the two
entry points is enumerated in §Out-of-scope follow-ups of the
workflow-primitives spec and is a candidate for a follow-up shape.

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
- `cli/`, `__main__.py`, `__init__.py` — entry points (`cli/` is a package holding
  per-subcommand modules; `cli.main:main` is the console-script entry)
- `config.py` — configuration loading (imported by almost everything)

Everything else earns its way into a package via the rules above.

## 7. Package markers — every package has `__init__.py`

**Every package has an `__init__.py`, even if empty.** a2sdlc uses regular packages
(PEP 328) consistently, not PEP 420 namespace packages. The file may be empty, a
docstring, or a public-API re-export — but it must exist.

**Why:** the codebase is a **mix** of packages that hold real content (`adapters/`,
`stages/`, top-level `a2sdlc/`) and packages that currently don't (`domain/`,
`pipeline/`, `lifecycle/`, `assembly/`, `evaluation/`). A mixed regular/namespace-package
state is the one configuration most likely to produce tooling surprises:

- hatchling's `packages = ["src/a2sdlc"]` expects a regular-package tree; missing
  `__init__.py` files can silently drop subpackages from the wheel.
- `import-linter` rules (see §7) target importable modules — regular packages are
  the unambiguous target.
- Type checkers, test runners, and coverage tools all handle both, but edge cases
  (re-import priority, `__all__` resolution) diverge.

The gain from dropping empty `__init__.py` files is aesthetic (≤ 0 bytes saved per
file); the risk is real. Keep them. If an `__init__.py` grows beyond empty, it
should re-export the package's **public API** (see §7 enforcement).

## 8. Enforcement

- **Lint:** `import-linter` config in `pyproject.toml` enforces the layering table in §2.
  Domain purity (`domain/` imports nothing from other a2sdlc packages) is the critical rule
  — CI must fail on violation.
- **Review heuristic:** if a PR adds a file to `src/a2sdlc/` root that isn't in the "what stays flat"
  list, the reviewer asks "what package does this belong to?" If the answer is "none yet," the PR
  creates that package.
- **Threshold check:** if any package (including the root) exceeds ~15 top-level files, split it
  along product-concern lines before adding a sixteenth.

## 9. When to reconsider this shape

- **Feature-slicing becomes warranted** when 3+ independent feature areas share no code. Example:
  a parallel "release notes" pipeline that doesn't touch `dispatch.py`. Then: `features/release_notes/`,
  `features/bug_triage/`, each self-contained. Not applicable today — the pipeline is one feature
  and stages are its variants.
- **Full DDD** becomes warranted when the domain has 3+ bounded contexts with divergent vocabularies.
  Not applicable today — the domain is one pipeline.

Until those triggers fire, this shape holds.
