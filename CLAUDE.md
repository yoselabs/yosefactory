# yosefactory

Personal workflow platform. Process workflows the operator runs their own work through — software first, but deliberately not limited to it — driven from Claude Code / Claude Desktop over MCP.

**Not** a product, **not** a framework for other people, **not** a general agent runtime. One user. If a design choice only makes sense for a second user, it is out of scope.

## Read this first

The design is done and lives elsewhere. Do not re-derive it.

**P160 is this repo's design authority, and it is a live reference an agent is expected to read from and write back to — not background reading.** Before proposing anything structural, look it up there. When the build contradicts it, correct it there. A session that builds without touching P160 either got lucky or skipped the check.

*The paths below are a local, private knowledge base — they resolve on the operator's machine only. If you are reading this from a clone, treat the entity ids (D014, H572, M600, …) as stable names for decisions recorded there, not as links you can follow.*

**Design record: project 160, at `~/Documents/Knowledge/Projects/160-ai-factory/`.** Three files, in this order:

| File | Read it when |
|---|---|
| `build-loop.md` | **first, every session.** The operating protocol: what to load, when to write back, how to close. Short. |
| `handover-2026-08-12-build.md` | the bootstrap brief — once, in full, before writing code, plus the nine entities it links |
| the corpus itself | never wholesale. 1,065 entities; reach for them via `tools/recall.py`, per `build-loop.md` |

Decisions are `decisions/D0NN-*.md`, arguments are `philosophy.md`, open structural questions are `tensions.md`.

## Success criterion

**D014**, authored by the operator before any code existed:

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
> **No** → `src/yosefactory/protocol/`, freeze it and make it small.

`protocol/` is meant to stay tiny. Rigidity there is cheap because the surface is small, and it is what makes everything above it replaceable. Resist growing it.

## Layout

```
src/yosefactory/
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

### How, concretely

**`P160/build-loop.md` is the procedure** — what to load at session open, the three triggers that force a write-back, what *not* to write back, and how to close. It is deliberately the only copy; the commands and the schema live over there and drift over there.

Two rules worth carrying here, because violating them costs a cleanup rather than a correction:

- **Never hand-number or hand-link an entity.** Parallel sessions have collided on ids twice. `capture.py` allocates; `wire.py` links both sides.
- **Two commits that name each other.** The commit here cites the entity ids it acted on or refuted; the K commit cites this repo's SHA. That is the entire cross-repo traceability mechanism.

## Constraints that travel with the code

- **D002** — nothing is ever deleted. Applies to `ledger/`, not to source.
- **D005** — no party outside the operator holds approval rights over what this work is, where it is published, or who may see it. Publishing is their call alone; commissioning is downstream of published receipts, never upstream permission.
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

## Communication

The one-line version: **drop words, keep facts.** Everything below is measured token-efficiency behaviour, not style preference.

**Scope: everywhere.** Reasoning and internal deliberation, agent-to-agent messages, user-facing replies, the documents this repo produces, and the code itself — comments, names, commit messages. One exception, below.

**ASCII diagrams are human-facing only.** Reach for one when a picture beats prose *for a person reading a reply*. Never in documents, code, commit messages, or agent-to-agent traffic: there a diagram is decoration that another model has to parse back into facts, and it survives edits badly.

This is not "no code blocks in documents". A directory tree, a schema, a command, a sample payload — anything whose literal shape *is* the content — belongs wherever it is clearest. The rule is against drawing a picture of an idea, not against showing a structure verbatim.

**Two axes, and they are not the same knob.**

| Axis | Means | When |
|---|---|---|
| Terse | compress words | always |
| Simple | lower assumed concepts | only when teaching something new |

A status update needs terse alone. An unfamiliar idea needs both. Applying "simple" to a status update reads as condescension; applying only "terse" to an explanation strips the scaffolding that made it land.

**Structure is the whole lever.** Bullets and labels (`Risk:` / `Fix:` / `Why:`) replace grammatical connectors and cut 38-42%. What disappears is scaffolding, not content. Never write unstructured prose in order to be concise - forcing prose *adds* ~22%, because the connective tissue that structure would have absorbed gets regenerated as words.

**Reporting -> verdict + link. Asking -> full context.**

| Situation | What the reader needs |
|---|---|
| Work is on disk | A pointer and what is *newly decidable*. Never restate a file you just wrote. |
| A decision is theirs to make | What it is, why it matters, the tradeoff. Compress the words, never the content. |

The first row is the one this repo's own history violated most: entities written to the knowledge base, then re-narrated at length in chat. The second is the failure in the other direction - terseness must never degrade into a bare identifier and *go look it up yourself*.

**Keep words plain.** Rare vocabulary costs ~75% more tokens and non-English 17-38%. UPPERCASE headers, caveman style, personas and Chain-of-Draft gimmicks either inflate tokens through rare-token splits or hit brevity targets by *dropping facts* - retention as low as 86%. Shared jargon is the one real lexical win (-29%): "idempotent" beats a sentence, cheaply. Emoji are fine as compression, where a status glyph beats a sentence; not as decoration.

**In code specifically.** Names carry the meaning, so comments do not repeat them. Write a comment only for a constraint the code cannot show - never to narrate what the next line does or to justify the change to a reviewer, which is noise the moment the branch merges. Commit messages: what changed and why it had to, not a tour of the diff.

**Terse trims elaboration, never correctness.** On hard and long-context work it retains ~98% of core facts. What it cuts on open-ended asks is analogies and worked examples - fine for technical work, wrong when someone is trying to *understand* something, where that scaffolding is the deliverable.

**Completeness wins on conflict.** This is a style default. A spec, a formal deliverable, or a decision record is written in full.

**Why:** an operator reading agent output across many parallel sessions pays a tax on verbose prose. But terseness that costs them a decision input is not a saving.
