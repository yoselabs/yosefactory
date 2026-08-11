# a2factory

Personal workflow platform. Process workflows Denis runs his own software work through, driven from Claude Code / Claude Desktop over MCP.

**Not** a product, **not** a framework for other people, **not** a general agent runtime. One user. If a design choice only makes sense for a second user, it is out of scope.

## Read this first

The design is done and lives elsewhere. Do not re-derive it.

- **`~/Documents/Knowledge/Projects/160-ai-factory/handover-2026-08-03-build.md`** — the bootstrap brief. Read it in full, then the nine entities it links under "Read before writing code".
- **`~/Documents/Knowledge/Projects/160-ai-factory/`** — the corpus. 1,065 entities. Decisions are `decisions/D0NN-*.md`, arguments are `philosophy.md`, open structural questions are `tensions.md`.

## Success criterion

**D014**, authored by Denis before any code existed:

- **Unit** — a commit to `~/Workspaces/a2web` produced through this platform.
- **Threshold** — 7 consecutive days without one.
- **Clock starts** — at the first such commit. Nothing is being measured before then.
- **Voids a gap** — travel, illness, family. *Not* paid-work crunch; that was offered and explicitly refused.
- **On breach** — root-cause the platform. Patching the gap is forbidden. Abandoning is refused.

Nothing else is the goal. Not elegance, not coverage, not feature count.

## The one structural rule

From `philosophy.md` C2, refined by P131 concept 09 into five layers:

> *If this changed next month, would existing ledger rows still be readable and comparable?*
> **Yes** → `workflows/`, keep it soft, versioned, disposable.
> **No** → `src/a2factory/protocol/`, freeze it and make it small.

`protocol/` is meant to stay tiny. Rigidity there is cheap because the surface is small, and it is what makes everything above it replaceable. Resist growing it.

## Layout

```
src/a2factory/
  protocol/    L1 — unit of work, states, ledger row shape, the typed question (M600)
  runtime/     L2 — Claude Agent SDK harness, hooks, session plumbing
  server/         — MCP surface. Thin. Exposes workflows and nothing else.
  workflows/   L3 — workflow implementations, when they stop being pure data
workflows/        — workflow definitions as data. Two, deliberately duplicated.
ledger/           — append-only run records
decisions/        — build-time ADRs only
```

## Where things go

| Kind of thing | Home |
|---|---|
| Source, build ADRs, workflow definitions, ledger | here |
| Signals, hypotheses, mechanisms, probes, tensions | P160 |
| A decision about **what to build and why** | P160 |
| A decision about **how it got built** | `decisions/` here |

**Write-back is mandatory** (D015). When the build falsifies a design entity — a mechanism that will not build as specified, a hypothesis the first run refutes, a suspension point that never materialises — write the correction into P160 **against the entity id**. The handover cites ids throughout precisely so this is possible.

## Constraints that travel with the code

- **D002** — nothing is ever deleted. Applies to `ledger/`, not to source.
- **D005** — lab-internal. A demo to [redacted] people intersects this and has not been re-checked.
- **D011** — the friction threshold. Before building any part of an adopted tool's job, all three must hold: a named blocked requirement (cited by entity id), a dated seam-failure receipt with the failure quoted, and a build that is a *predicate* rather than a replacement. Prediction is not a receipt.
- **D012** — the corpus does not move into an external tool. This repo does not absorb P160.
- **D013** — every adoption candidate gets a dated coverage receipt. That includes `claude-agent-sdk` and Managed Agents.

## Do not build

Web UI or dashboard (D110) · own harness (D104) · multiple harnesses behind a seam · Telegram surface (D007) · LangGraph/LangSmith · daemon, orchestrator, or queue (D111) · skill auto-creation by research (philosophy C6) · anything with a second user in mind (S041).

Each has a revisit trigger recorded in the handover. Triggers fire on evidence, not on enthusiasm.

## Reuse before writing

Checking whether a process already exists is the cheapest high-yield move available (S056), and this fleet has five shaped-and-unbuilt projects proving the cost of skipping it (S091).

- **`~/Workspaces/a2skill`** — built, working, Python. MCP server + CLI that discovers and loads skills from a catalog. This is skill lookup, already shipped. **Do not rewrite it.** Copy its packaging shape.
- **`~/Workspaces/shelf`** — 26 packages, the ledger format, the rule-of-three promotion rule. D001: the shelf is part of the factory.
- **`~/Documents/Knowledge/Projects/131-bureaucracy-framework/`** — the layer model, the evidence model, five 14-section workflow runbooks.
- **`~/Documents/Knowledge/Researches/087-process-mining-skills-evolution/synthesis.md`** — the skill-evolution research, including negative-feedback priority and the verification gate.

## Method

**H572** — the substrate is *extracted from two deliberately duplicated workflows*, not designed ahead of them. Write both, run both on real a2web work, then take only what turns out identical. Duplication is the instrument; removing it early destroys the measurement.

**T17** is open: is a workflow a list of stages, or something else? It is answered by reading the diff, not by arguing.

## Stack

Python ≥3.11, `uv`, `ruff`, `ty`, `pytest`. `make check` runs lint + types + tests.

`claude-agent-sdk` is the harness — Claude Code as a library. It is **not** the Anthropic API SDK's `client.beta.messages.tool_runner`; the two are different packages with different scope. Docs: `code.claude.com/docs/en/agent-sdk`.

Model: `claude-opus-5`, adaptive thinking, effort `high` default, `xhigh` for long agentic runs.
