# a2sdlc — Design Process

**Date:** 2026-04-22
**Status:** Draft for review
**Scope:** The documents, artifacts, and checkpoints a team producing / using a2sdlc goes through from idea to merged-and-observed code.

This document defines **how we work**, not what we're building. It sits between the product vision (why) and the architecture vision (how, at the engine level). It is the connective tissue that tells contributors — human and agent — what document to write next, what to review, and what "done" means at each phase.

The process is **medium-weight**: rigorous enough to scale from 1 engineer to ~20 without re-inventing itself, light enough that a solo developer in flow can still use it without drowning in ceremony.

---

## 1. Design goals for the process itself

Before picking a shape, name what "a good process" must do for us:

| # | Goal | Consequence |
|---|---|---|
| G1 | **Traceability** — every line of code can be traced back to a decision and a reason. | ADRs, specs, PRs, commits all cross-link. |
| G2 | **Right-sized ceremony** — a one-day fix should not require a 12-section RFC. | Steps are **optional by default**, escalated by scope. |
| G3 | **Agent-friendly** — an AI agent should be able to author, consume, and link these docs. | Structured templates with predictable sections. |
| G4 | **Scales from 1 to 20** — same shape works solo or with a small team. | No bureaucratic gates (no "architecture review board"). |
| G5 | **Eval-native** — every change can be tied to a measurable outcome. | Eval plans are first-class for prompts/stages. |
| G6 | **Eventually-consistent docs** — docs never block shipping, but they never fall behind by more than one cycle. | Post-merge retro is mandatory if pre-merge docs were skipped. |
| G7 | **Retro-fed** — what we learned feeds back into shaping. | Closed loop, not open-ended doc production. |

---

## 2. Research — what proven processes look like

A brief survey of relevant prior art. Citations summarize what each brings to the table, not full endorsement.

### 2.0 A note on synthesis — Shape Up vs RFC/RFD

Shape Up (§2.1) and RFC culture (§2.2–2.3) start from opposite premises. Shape Up explicitly *rejects* pre-commitment design documents in favor of shaped pitches + implementer autonomy. RFC culture commits design in depth before implementation.

We keep both, deliberately. The resolution:

> **The pitch sets the fence** — scope, appetite, rabbit holes, no-gos. Implementers have autonomy inside the fence.
> **The RFC lives inside the fence** — only for technical commitments that affect shared surface: Protocols, the composition root, cross-package contracts, wire formats. RFCs do not re-open scope; they commit technical shape.

At team size 1, pitches + specs do the RFC's job. RFCs appear when more than one person has to align on a technical commitment.

### 2.1 Shape Up (Basecamp, 2019)

- **Core idea:** *shape* work before committing. Output is a "pitch" with fixed appetite (1 or 6 weeks), rough solution sketch, rabbit holes, no-gos. Betting table chooses which pitches to build.
- **Why it matters:** forces scope discipline *before* coding. Distinguishes "problem explored" from "solution chosen."
- **Takeaway for us:** adopt the **pitch** as the first formal artifact. Keep the appetite idea; drop the betting table (too heavy for our size).

### 2.2 RFC / Request For Comments (IETF, later Rust, Python, React)

- **Core idea:** any substantial change gets a numbered proposal document open for comment. Merged when accepted.
- **Why it matters:** makes the *discussion* durable, not just the decision.
- **Takeaway:** use the RFC format for **design documents** — but don't formalize a voting process. Comments on the PR are enough at our size.

### 2.3 Oxide RFDs (Requests for Discussion)

- **Core idea:** variant of RFCs with stronger lifecycle (prediscussion → discussion → published → committed → abandoned). Every RFD is numbered, stored in git, lifecycle-labeled.
- **Why it matters:** solves the "where does half-baked thinking go?" problem.
- **Takeaway:** borrow the **lifecycle states** for design docs. Draft → Review → Accepted → Implemented → Superseded.

### 2.4 Nygard ADRs (2011)

- **Core idea:** a short doc (< 1 page) per *decision*. Format: Context / Decision / Consequences / Alternatives.
- **Why it matters:** decisions outlive discussions. An ADR preserves "why we did X and not Y" for future engineers asking the same question.
- **Takeaway:** already adopted (see `docs/adr/`). Extend coverage: every architectural change needs an ADR, not just the big ones.

### 2.5 Google design docs

- **Core idea:** one long doc per project, written before implementation. Covers objective, background, design, alternatives, testing, open questions.
- **Why it matters:** single canonical document that evolves with the work.
- **Takeaway:** our "spec" role. Keep it one document per feature; let it evolve.

### 2.6 Amazon working-backwards / PRFAQ

- **Core idea:** write the press release and FAQ *before* building. Forces customer clarity.
- **Why it matters:** surfaces "why does anyone care?" at the earliest stage.
- **Takeaway:** borrow **a compressed PR-FAQ section** inside the pitch for customer-facing features — not as a separate doc. Internal refactors skip it.

### 2.7 C4 model (Simon Brown)

- **Core idea:** diagrams at four levels — System context → Container → Component → Code.
- **Why it matters:** gives a consistent visual vocabulary for "where does this change live?"
- **Takeaway:** require at least a **container-level diagram** in every design doc. Code-level diagrams are usually overkill.

### 2.8 arc42

- **Core idea:** 12-section architecture template covering everything from stakeholders to quality goals to risks.
- **Why it matters:** comprehensive checklist.
- **Takeaway:** **do not adopt wholesale** — too heavy. But use arc42 as a checklist to verify our design doc template covers the important axes.

### 2.9 BMad Method (AI-era SDLC)

- **Core idea:** AI-driven SDLC with analyst / PM / architect / dev / QA agents producing structured deliverables; "Agent Record" section inside each story.
- **Why it matters:** treats agents as first-class authors; expects docs to be machine-readable.
- **Takeaway:** our process must treat agent-authored docs as valid. Templates use consistent frontmatter and section headings so agents can parse them.

### 2.10 GitHub SpecKit (2024)

- **Core idea:** spec-driven development where the spec is the primary artifact and code is derived from it.
- **Why it matters:** aligns with a2sdlc's SPEC stage — the engine itself uses a SpecKit-ish flow internally.
- **Takeaway:** our implementation spec template doubles as the SPEC-stage output format. Dogfood-friendly.

### 2.11 Linear method

- **Core idea:** lightweight cycles (2 weeks), issues as the primary unit, minimal documentation overhead.
- **Why it matters:** counterweight to heavy RFC cultures.
- **Takeaway:** for bug fixes and small features, nothing above a tracker ticket is required.

---

## 3. The process chain

Nine document types, each serving a specific step. Not every change produces all nine — §4 defines which are mandatory when.

```
                    ┌─────────────────────────────────────────────────┐
                    │                                                 │
                    ▼                                                 │
                                                                      │
(0) Product Brief ──► (1) Pitch ──► (2) Design Doc ──► (3) ADR(s)     │
                                           │                          │
                                           ▼                          │
                                   (4) Implementation Spec            │
                                           │                          │
                                           ▼                          │
                                   (5) Eval Plan                      │
                                           │                          │
                                           ▼                          │
                                   ┌───────┴──────┐                   │
                                   ▼              ▼                   │
                               CODE + PR    (6) Runbook               │
                                   │                                  │
                                   ▼                                  │
                           (7) Changelog ──► (8) Retro / Postmortem ──┘
```

Each step below defines purpose, format, owner, length, lifecycle, and failure mode ("what happens if skipped").

### (0) Product Brief

- **Purpose:** capture a problem worth solving, before exploring solutions.
- **Format:** 1 page. Problem / Why now / Who feels it / Rough success signal.
- **Owner:** product owner (today: @iorlas).
- **Length:** ≤ 500 words.
- **Lifecycle:** Draft → Accepted → Archived (once converted to pitches or rejected).
- **Location:** `docs/briefs/YYYY-MM-DD-<slug>.md`.
- **Mandatory for:** strategic initiatives only (new product areas, major pivots). Skipped for internal refactors and maintenance.
- **Skipped →** team builds things no customer wants.

### (1) Pitch (Shape Up style)

- **Purpose:** shape a problem into a bounded, implementable chunk with a declared appetite.
- **Format:** Problem / Appetite (hours/days/weeks) / Solution sketch / Rabbit holes / No-gos / Nice-to-haves.
- **Owner:** the person who will lead the work, in collaboration with product owner.
- **Length:** 1–3 pages.
- **Lifecycle:** Shaping → Bet → Building → Shipped / Abandoned.
- **Location:** `docs/pitches/YYYY-MM-DD-<slug>.md`.
- **Mandatory for:** anything taking more than 1 week of work.
- **Skipped →** scope creep, missed trade-offs, projects that run 3× over.

### (2) Design Doc (RFC)

- **Purpose:** commit to a specific solution in enough depth that implementation is mechanical.
- **Format:** Context / Goals / Non-goals / Design (with C4 container-level diagram) / Alternatives / Trade-offs / Risks / Open Questions.
- **Owner:** the technical lead for the work.
- **Length:** 3–10 pages.
- **Lifecycle:** Draft → In review → Accepted → Implemented → Superseded (by RFD number).
- **Location:** `docs/rfcs/NNNN-<slug>.md` (sequential number).
- **Mandatory for:** anything spanning ≥ 2 packages, changing a public interface, or touching the composition root.
- **Skipped →** implementations that miss the point, rework late, architectural erosion.

### (3) ADR

- **Purpose:** record a specific decision and its rationale, extracted from the design doc so future engineers can find it.
- **Format:** Context / Decision / Consequences / Alternatives (per Nygard).
- **Owner:** whoever made the decision.
- **Length:** < 1 page.
- **Lifecycle:** Proposed → Accepted → Superseded (by ADR number).
- **Location:** `docs/adr/NNNN-<slug>.md` (already established).
- **Mandatory for:** every decision referenced by a design doc; also standalone decisions not triggered by a project (tooling, linting rules, etc.).
- **Skipped →** "why did we do it this way?" questions with no answer, silent drift.

### (4) Implementation Spec

- **Purpose:** break a design doc into a concrete implementation plan — what files, what tests, what sequence.
- **Format:** Goal / Non-goals / Step-by-step plan with TDD checkpoints / Rollout / Test strategy / Backout.
- **Owner:** implementer (human or agent).
- **Length:** 2–5 pages.
- **Lifecycle:** Draft → Approved → Executed → Done.
- **Location:** `docs/superpowers/specs/YYYY-MM-DD-<slug>-design.md` (already established).
- **Mandatory for:** anything the Superpowers / BMad / a2sdlc SPEC stage produces. Fits naturally as the SPEC stage output.
- **Skipped →** implementation gets ad-hoc; agents produce inconsistent artifacts; hard to review.

### (5) Eval Plan

- **Purpose:** for AI-touching changes, declare how we'll measure whether the change improved outcomes.
- **Format:** Hypothesis / Metrics / Fixture set / Baseline / Pass criteria / Rollback criteria.
- **Owner:** the person making the change.
- **Length:** 1–2 pages.
- **Lifecycle:** Draft → Running → Analyzed → Decision made.
- **Location:** `docs/evals/YYYY-MM-DD-<slug>.md` (new folder).
- **Mandatory for:** any change to a stage prompt, stage runner, model selection, agent framework integration. Required by product principle P-03 ("every run is measurable").
- **Skipped →** prompt changes ship on vibes; regressions go undetected; no credibility.

### (6) Runbook

- **Purpose:** operational instructions for maintaining, debugging, recovering a component.
- **Format:** Purpose / Dashboards / Alerts / Common failures + remedies / Escalation / Rollback.
- **Owner:** the feature owner.
- **Length:** 1–3 pages.
- **Lifecycle:** living document.
- **Location:** `docs/runbooks/<component>.md`.
- **Mandatory for:** anything running as a service (dispatcher, future SaaS), anything with a persistent failure mode (stuck comments, stale state).
- **Skipped →** on-call pages with no playbook; tribal knowledge; regressions on shift changes.

### (7) Changelog

- **Purpose:** tell users what changed, in their language.
- **Format:** Added / Changed / Deprecated / Removed / Fixed / Security.
- **Owner:** release driver.
- **Length:** a few bullets per release.
- **Lifecycle:** append-only per release.
- **Location:** `CHANGELOG.md`.
- **Mandatory for:** every release that ships code users depend on.
- **Skipped →** users miss critical behavior changes; support load spikes.

### (8) Retro / Postmortem

- **Purpose:** extract learnings and feed them back into future shaping.
- **Format:** What happened / What went well / What didn't / What we'll do differently / Action items (with owner and due date).
- **Owner:** project lead.
- **Length:** 1–2 pages.
- **Lifecycle:** written within 1 week of ship; closed when action items complete.
- **Location:** `docs/retros/YYYY-MM-DD-<slug>.md`.
- **Mandatory for:** (a) anything that shipped late by > 50% of appetite; (b) anything customer-visible that failed; (c) every quarter regardless.
- **Skipped →** same mistakes recur; no learning; planning stays bad.

---

## 4. Which documents are mandatory, by change size

**At team size ≥ 3**, use this matrix:

| Change type | 0 Brief | 1 Pitch | 2 RFC | 3 ADR | 4 Spec | 5 Eval | 6 Runbook | 7 Changelog | 8 Retro |
|---|---|---|---|---|---|---|---|---|---|
| **Typo / copy edit** | — | — | — | — | — | — | — | opt. | — |
| **Bug fix, < 1 day** | — | — | — | — | opt. | — | — | ✅ | — |
| **Small feature, < 1 week** | — | opt. | — | — | ✅ | if AI | — | ✅ | — |
| **Medium feature, 1–4 weeks** | — | ✅ | ✅ | per-decision | ✅ | if AI | if ops | ✅ | conditional |
| **New subsystem / bounded context** | opt. | ✅ | ✅ | ✅ | ✅ | if AI | ✅ | ✅ | ✅ |
| **Strategic initiative** | ✅ | ✅ (multiple) | ✅ | ✅ | ✅ | if AI | ✅ | ✅ | ✅ |
| **Prompt or agent-runner change** | — | opt. | — | — | ✅ | ✅ | — | ✅ | conditional |
| **Incident / production failure** | — | — | — | — | — | — | — | ✅ | ✅ |

**At team size 1 (solo), the above matrix is overridden.** The minimum chain is:

| Change type | Required docs |
|---|---|
| **Anything ≤ 1 day** | (nothing — commit message is enough) |
| **Anything taking more than 1 day** | Spec |
| **Anything AI-touching (prompts, stage runners, models)** | Spec + Eval |
| **Anything changing a Protocol or touching the composition root** | Spec + ADR (for the decision) |
| **Anything ≥ 1 week** | Pitch + Spec (+ Eval if AI) |
| **RFC** | **Opt-in only.** Triggered when you need to talk yourself through a design or hand off to collaborators. Not mandatory at team size 1. |

The solo carve-out is not a lowering of standards — it is a recognition that at team size 1, **Pitch + Spec already encodes what an RFC would, without ceremony**. When the team grows past 1, the full matrix applies.

"opt." = optional, writer's discretion. "conditional" = mandatory if triggering conditions from §3.8 met.

---

## 5. Lifecycle states — shared across document types

Borrowed from Oxide RFDs, simplified:

| State | Meaning | Allowed transitions |
|---|---|---|
| **Draft** | Author is thinking out loud; not ready for feedback. | → In Review, → Abandoned |
| **In Review** | Open for comments; expected to converge. | → Accepted, → Abandoned, → Draft |
| **Accepted** | Decision made; implementation can start. | → Implemented, → Superseded |
| **Implemented** | Work shipped; doc is historical record. | → Superseded |
| **Superseded** | Replaced by newer doc; kept for audit trail. | (terminal) |
| **Abandoned** | Explicitly not pursuing. | (terminal) |

The lifecycle state lives in YAML frontmatter on every document:

```yaml
---
title: "Inline PR Code Review"
type: rfc          # brief | pitch | rfc | adr | spec | eval | runbook | retro
number: 0007       # sequential per type
status: In Review  # Draft | In Review | Accepted | Implemented | Superseded | Abandoned
owner: "@iorlas"
created: 2026-04-22
updated: 2026-04-22
supersedes: null
superseded_by: null
---
```

---

## 6. Cross-linking — the chain is only as good as its links

Every document MUST link back to its antecedents and forward to its consequences:

| Document | Links back to | Links forward to |
|---|---|---|
| Pitch | Brief (if any), product vision | Design doc |
| Design doc | Pitch, product vision | ADRs, implementation specs |
| ADR | Design doc (if extracted) | Implementation specs that depend on it |
| Implementation spec | Design doc, relevant ADRs | PR(s) that implement it |
| Eval plan | Spec being evaluated | Result summary, changelog entry |
| PR | Implementation spec, eval plan | Changelog entry |
| Changelog entry | PR, spec | — |
| Retro | Pitch, spec(s), changelog | Future pitches (action items) |

A link-checker lint rule should enforce this. Broken links fail CI.

---

## 7. Ownership and authorship — humans and agents

**Both humans and AI agents may author every document type.** The template frontmatter identifies the author:

```yaml
author:
  human: "@iorlas"
  agent: "claude-sonnet-4-6 via Superpowers brainstorming skill"
  co_authors: ["@collaborator"]
```

**Review requirement:** every document reaches "Accepted" only after at least one *human* has reviewed it. Agents may draft and refine; humans accept. This enforces product principle P-01 ("humans decide").

**Agent-friendly format rules:**
- Consistent section headings (as specified in templates).
- YAML frontmatter on every document.
- Links use relative paths, not slugs.
- No ASCII art in machine-parsed sections (diagrams go in clearly-demarcated blocks).
- Tables for structured data.

---

## 8. Tooling

Each stage needs tooling to be usable at scale. Today we have some; the rest is planned.

| Stage | Tooling today | Tooling planned |
|---|---|---|
| Brief | none | template + CLI scaffold |
| Pitch | none | template + CLI scaffold |
| RFC | none | template + CLI; link-checker |
| ADR | existing convention in `docs/adr/` | CLI for `adr new <slug>`; auto-numbering |
| Spec | Superpowers specs under `docs/superpowers/specs/` | Consistent template frontmatter; generated from SPEC stage |
| Eval | none | template + MLflow integration; fixture replay CLI |
| Runbook | none | template |
| Changelog | `CHANGELOG.md` manual | semantic-release integration (optional) |
| Retro | none | template |

A single `make docs-new <type> <slug>` command should scaffold the right template into the right folder with correct frontmatter.

---

## 9. How the process scales

### 1 engineer

Brief + Pitch + Spec + Eval for AI work. Skip RFC (design flows into spec). Skip retro unless incident.

### 3–5 engineers

Full chain on medium features. RFCs for anything touching shared subsystems. Weekly informal retros, formal retros per quarter.

### 10+ engineers

Add weekly RFC review hour. Require ADRs for every decision that affects > 1 team. Require runbooks for every on-call-able component. Retros are cross-team.

### 20+ engineers

Introduce RFC accept-authority (tech leads per area). Formalize the betting table (quarterly appetite allocation). Split process owner from individual contributors.

---

## 10. Dogfooding — a2sdlc consuming its own process

Because a2sdlc *is* an AI SDLC pipeline, each document type maps onto the engine's own stages when run on its own codebase:

| Process doc | a2sdlc stage producing it |
|---|---|
| Pitch | `EPIC_SHAPING` stage (planned) |
| RFC / Design doc | `SPEC` stage produces it as its primary artifact |
| ADR | `SPEC` stage can fork one per decision |
| Implementation spec | `SPEC` stage's secondary artifact (plan.md) |
| Eval plan | Authored alongside SPEC when stage is AI-touching |
| Code | `IMPLEMENT` stage |
| Runbook | Manually authored, possibly by a future `DEPLOY` stage |
| Retro | Manual — the human loop |

This alignment is intentional. The engine's stages ARE the SDLC process stages, so a2sdlc's own engineering uses the engine's output format as its internal format.

---

## 11. Anti-patterns to avoid

From the research survey and hard-won lessons, named so we don't drift into them:

| Anti-pattern | Symptom | Counter |
|---|---|---|
| **Documentation as performance** | Docs written to look thorough, never read. | Every doc has named readers; unread sections get cut. |
| **Drive-by design review** | RFCs sit open for weeks; no decision. | SLA: RFC in-review for > 7 days → owner convenes decision or closes. |
| **Specs rotting post-ship** | Specs describe what was supposed to happen, not what did. | Either update spec on divergence or close-and-write-new. |
| **Decision amnesia** | "Why did we do X?" has no answer. | ADRs mandatory; linked from code comments for non-obvious choices. |
| **Retro theatre** | Retros with no action items, or action items with no owners. | Every retro item has owner + due date; next retro reviews last cycle's items. |
| **RFC in the wrong direction** | Design doc written *after* implementation started. | Allowed once — second occurrence triggers a process retro. |

---

## 12. Migration to this process — for a2sdlc itself

We're not starting from zero. This process retrofits onto existing docs:

| Existing | Becomes |
|---|---|
| `docs/architecture.md` | Living **current-state doc**; stays at top level. |
| `docs/architecture-vision.md` | Moved to `docs/vision/02-architecture-vision.md`. |
| `docs/adr/*` | Unchanged — already the ADR folder. |
| `docs/superpowers/specs/*` | Becomes the implementation-spec folder. Frontmatter normalized over time. |
| `README.md` doc index | Updated to link to `docs/vision/`. |

New folders to create incrementally (empty until first doc lands):
- `docs/briefs/`
- `docs/pitches/`
- `docs/rfcs/`
- `docs/evals/`
- `docs/runbooks/`
- `docs/retros/`
- `docs/templates/`

Migration has no deadline. New work uses the new shape; old docs stay where they are until touched.

---

## 13. Open decisions

(Renamed to `PROC-*` to avoid collision with product principles `P-*`.)

| # | Decision | Options | Recommendation |
|---|---|---|---|
| PROC-01 | **RFC vs. design-doc naming.** | (a) keep both; (b) fold into one called "Design Doc"; (c) fold into one called "RFC". | (c) — RFC is the more recognized term at scale. |
| PROC-02 | **Numbering scheme.** | (a) `NNNN` sequential per type; (b) `YYYY-MM-DD-slug` per type. | (a) for RFC/ADR (stability matters), (b) for briefs/pitches/retros (date-scoped matters). |
| PROC-03 | **Where do eval fixtures live?** | (a) in-repo under `docs/evals/`; (b) separate fixture monorepo (per `project_a2sdlc_eval_system`). | (b) — matches existing plan; `docs/evals/` holds eval *plans* only. |
| PROC-04 | **Do we enforce agent-vs-human review split?** | (a) yes, always; (b) yes for Accepted state only; (c) no. | (b) — agents may edit drafts; humans accept. Aligns with product P-01. |
| PROC-05 | **Do we mandate eval plans for prompt changes?** | (a) yes, hard gate; (b) soft recommendation. | (a) once the eval harness is in place; (b) until then. |

---

## 14. Relationship to other docs

| Doc | Role |
|---|---|
| [`01-product-vision.md`](01-product-vision.md) | Provides the *why*. The process serves it. |
| [`02-architecture-vision.md`](02-architecture-vision.md) | Provides the *engine shape*. RFCs and specs live under its constraints. |
| [`../adr/`](../adr/) | Step (3) of this chain. |
| [`../superpowers/specs/`](../superpowers/specs/) | Step (4) of this chain. |
| [`../templates/`](../templates/) | Skeletons for steps (0) through (8). |
