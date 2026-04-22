# a2sdlc Vision Chain

A layered set of documents. Each expands the one above it. Read top-down to understand *why*, then *how we work*, then *how the engine is shaped*.

| # | Document | Scope | Primary audience |
|---|---|---|---|
| 01 | [`01-product-vision.md`](01-product-vision.md) | **Why** a2sdlc exists, who it's for, what "winning" looks like, what it is not. | Product, founders, strategic contributors. |
| 02 | [`02-architecture-vision.md`](02-architecture-vision.md) | **How** the engine is shaped to survive 12–18 months of growth against named vectors. Patterns, bounded contexts, migration phases. | Engineering, technical contributors, integrators. |
| 03 | [`03-design-process.md`](03-design-process.md) | **How we work** — the document chain from idea to shipped feature. Medium-weight, agent-friendly, scales 1 → 20 engineers. | Everyone who produces or reviews work. |

## Downstream artifacts

| Folder | Step | Role |
|---|---|---|
| [`../briefs/`](../briefs/) | (0) | Product briefs — problems worth solving |
| [`../pitches/`](../pitches/) | (1) | Shaped work with bounded appetite |
| [`../rfcs/`](../rfcs/) | (2) | Design docs in depth, with alternatives |
| [`../adr/`](../adr/) | (3) | Architecture decision records |
| [`../superpowers/specs/`](../superpowers/specs/) | (4) | Implementation specs |
| [`../evals/`](../evals/) | (5) | Eval plans for AI-touching changes |
| [`../runbooks/`](../runbooks/) | (6) | Operational runbooks |
| [`../retros/`](../retros/) | (8) | Retros and postmortems |
| [`../templates/`](../templates/) | — | Skeletons for each of the above |

## Reading order

- **New contributor:** 01 → 02 → 03 → dive into templates and existing specs.
- **Deciding a feature:** 01 (does it fit the mission?) → 02 (does it fit the engine?) → 03 (which documents do I need to write?).
- **Proposing an architecture change:** 02 (is it consistent?) → write an RFC → extract ADR(s).
- **External audience (investor / partner):** 01 + the positioning PDF (`../a2sdlc-positioning.pdf`).

## Active downstream work

- [`../pitches/2026-04-23-v1-scope.md`](../pitches/2026-04-23-v1-scope.md) — V1.0 scope pitch (4–6 week appetite).
- [`../rfcs/0001-v1-scope.md`](../rfcs/0001-v1-scope.md) — RFC-0001 formalizing the V1.0 scope matrix (IN vs POSTPONED for N1–N9, phases P1–P8, stages, trackers, gates, sinks).

## Status

| Doc | Status | Owner | Last reviewed |
|---|---|---|---|
| 01 Product vision | Draft | @iorlas | 2026-04-22 |
| 02 Architecture vision | Draft | @iorlas | 2026-04-22 |
| 03 Design process | Draft | @iorlas | 2026-04-22 |

The vision documents are **living**. When reality diverges, update them — don't let them rot into fiction.

## Relationship to `docs/architecture.md`

`docs/architecture.md` describes the **current** engine shape and its enforced rules. `02-architecture-vision.md` describes the **target** shape. During the migration they coexist; after migration completes, `architecture.md` is updated to describe the new current shape and the vision doc is archived.

## One-paragraph summary of each doc

**01 Product Vision.** a2sdlc is an **AI factory of agents** — the assembly line, quality control, and audit trail that turns tickets into merged code. OSS, two distributions: **CI edition now**, Temporal edition later. Serves small shipping teams (2–15 engineers) on GitHub / GitLab / Jira / local. **Eight product principles** — P-06 "real-CI-integration grade," P-07 "built by agents, for agents," P-08 "5-minute onboarding gate." Scope fence (§9) names what is **now**, **later**, and **not in vision** — closed D-01 (OSS, two editions), explicit non-goals for auth, SaaS, multi-tenancy, web UI.

**02 Architecture Vision.** Five patterns on hexagonal-lite: pipe-and-filter composition root, Strategy for stages (each runnable standalone), effects as transient data consumed by interpreter, middleware onion, functional-core discipline. Twelve bounded-context packages; three load-bearing types (`Event`, `StageHandler`, `Effect`). Declarative workflow YAML — stages, skills, models, transitions, subagents all config-driven. Subagents modeled as flat event stream with `agent:` prefix (SDK max-depth-2). `CompositionProfile` collapses Mode 1 / Mode 2. **Nine near-term commitments** (N1–N9: inline PR review, subtasks, worktrees, security-every-stage, backpropagation, standalone stages, QA strategy, two-GitHub-Apps identity, attacker model). Four horizon commitments (H1–H4). **Seven-layer QA strategy** (§13) closes the fake-adapter-to-real-CI gap. Observability: MLflow used idiomatically (experiment → run per ticket+variant → nested run per stage → trace → spans); subscriber bus is the only abstraction, Kafka/HTTP slot-fits.

**03 Design Process.** Nine document types — brief, pitch, RFC, ADR, spec, eval plan, runbook, changelog, retro — with clear chain, lifecycle states, cross-linking. Medium-weight by construction, **with a solo-owner override** that reduces to Pitch + Spec (+ Eval if AI) at team size 1. Synthesized from Shape Up + RFC/RFD + Nygard ADR + C4 + arc42 + BMad + SpecKit. Shape Up vs RFC conflict resolved: pitch sets the fence, RFC lives inside it for Protocol-level commitments.
