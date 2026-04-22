# a2sdlc — Product Vision

**Date:** 2026-04-22
**Status:** Draft for review
**Owner:** @iorlas
**Horizon:** 12–36 months

This is the top of the vision chain. It answers *why* a2sdlc exists, *who* it serves, *what good looks like*, and *what it is not*. Everything downstream — the architecture vision, ADRs, specs — must serve the answers here. When something downstream stops serving these answers, revisit this doc, not the downstream.

Placeholders `[DECIDE: …]` mark product decisions the owner has not yet committed to. They should be closed before this document leaves draft.

---

## 1. The problem

Software teams have more AI coding power than they can harness. The bottleneck is not the models — it is the **operational distance between an idea and merged code**. That distance is still crossed by humans, one manual click at a time:

- A ticket is written, but nobody decomposes it into an implementable spec.
- A branch is created, but nobody watches it through review.
- Feedback arrives on a PR, but nobody routes it back to the author.
- A review is approved, but nobody triggers the next step.
- A stage produces output, but nobody measures if it got better or worse.

Generic agents (Copilot, Cursor, raw Claude) are good at **episodes** — "implement this one thing." They are bad at **sustained pipelines** — "turn this ticket into a merged PR, with accountability at every stage, and do it the same way tomorrow." Existing orchestration systems (BMAD, Superpowers, SpecKit) are closer, but they are prompt frameworks, not running engines — they assume a human is driving the loop.

**The unmet need:** a running engine that takes a ticket board event and drives it — through spec, implementation, review, merge, and deploy — without a human in the per-ticket loop, while remaining **transparent, measurable, and safely bounded.**

---

## 2. Mission

> **a2sdlc is an AI factory of agents** — the assembly line, quality control, and audit trail that turns tickets into merged code.

Agent frameworks (Claude Agent SDK, Superpowers, BMad, SpecKit, raw prompts) are the **machines** on the line. The factory owns the routing, the stages, the measurement, the accountability — everything that surrounds the machines so they can produce reliable output at scale.

### The factory metaphor, concretely

| Factory concept | a2sdlc equivalent |
|---|---|
| Assembly line | The stage pipeline (Spec → Implement → Review → Merge → Deploy) |
| Machines / workers | Agent frameworks, swappable per stage |
| Raw material | Tickets (GitHub Issues, GitLab Issues, Jira) |
| Finished product | Merged PRs with audit trail |
| Quality control | The evaluation system (metrics, fixture replay, eval plans) |
| Line supervisor | Humans who approve gates, answer questions, set policy |
| Factory floor | Your existing CI pipeline (GitHub Actions, GitLab CI) |

### What this means in one sentence

> **Remove humans from the per-ticket loop — without removing them from the decisions.**

The factory runs itself. Humans approve the things that need approving.

---

## 3. Who we serve

### 3.1 Primary persona — "the small shipping team"

A 2–15 engineer team that:
- Uses GitHub (Issues + repo) or Jira (tickets) + GitHub (code) today.
- Ships real code to production, not prototypes.
- Already uses AI tools individually (Copilot, Cursor, Claude), but not **team-wide**.
- Feels the pain of "we have more backlog than we have time to push through" — and cannot hire out of it.
- Has a senior engineer or tech lead who wants **control**, not magic.

Why them first:
- Small enough to adopt without committee approval.
- Large enough to feel the per-ticket-loop cost.
- Technical enough to configure an engine, not demand a SaaS click-button.

### 3.2 Secondary persona — "the solo founder / senior IC"

One person shipping a product with AI assistance. Wants the engine's discipline (stages, observability, cost ceilings) without any team coordination cost. Local-execution mode serves them.

### 3.3 Anti-persona — who we do NOT serve

- **"Magic button" buyers** — people who want AI to ship production software without configuration, without a staging pipeline, without code review. a2sdlc assumes you have an SDLC; it does not invent one for you.
- **Legacy-first enterprises** — heavy procurement, compliance-first, ticket trackers we don't integrate with. Serve them when the engine is mature enough to warrant the implementation cost on our side.
- **Non-technical PMs driving the tool directly.** The tool is developer-first. PMs interact through tickets, not through a2sdlc itself.

---

## 4. What "winning" looks like

### 4.1 Near-term (12 months) — product-market signal

- **100+ repos** installing a2sdlc as a GitHub App or dispatcher integration.
- **Median ticket** (small bug, small feature) goes from "agent-labeled" to "PR ready for human merge" in under an hour, without human intervention between stages.
- **At least 60%** of merged tickets in active repos went through a2sdlc, not a human IDE.
- **Measurable regression detection:** engine evaluation harness catches prompt regressions before they ship — we can say "this change degrades SPEC quality by X%" with numbers.
- **Content traction:** a2sdlc becomes the reference implementation that other people cite when talking about AI SDLC pipelines. (Related: `project_content_strategy`.)

### 4.2 Horizon (36 months) — category definition

- **The default answer** for "how do you run an AI coding pipeline with accountability?" is a2sdlc or an explicitly-chosen alternative — not "we wrote our own workflow."
- The engine is **tracker-agnostic** in practice, not just in architecture: healthy GitHub, Jira, Linear deployments.
- The **evaluation harness** is the selling point as much as the pipeline. Teams adopt a2sdlc *because* they can measure prompt iteration against real tickets.
- The pipeline pattern extends past code: **security reviews, release notes, epic shaping, deploy** all run on the same engine.

### 4.3 What we are NOT optimizing for

- Being the best single-turn coder (Copilot does that).
- Being the best agent framework (Superpowers / BMAD do that).
- Being the best LLM observability platform (Langfuse / Arize do that).
- Being the cheapest option (cost-per-ticket matters, but discipline + measurability matter more).
- Zero-config UX. We assume a `.a2sdlc/config.yaml` exists and that users can edit YAML.

---

## 5. Product principles

Five principles that should settle most design debates.

### P-01 — Humans decide; the engine routes.

Every stage exists to either produce an artifact (spec, code, review) or to route decisions back to humans (gate approvals, questions, policy exceptions). The engine never **decides** that a merge is safe; it executes merges that have been authorized. This principle rules out "autonomy creep" where the engine silently starts making product decisions.

### P-02 — The factory owns the line; the agents are swappable workers.

We build the factory, not the workers. Claude Agent SDK is the first-class machine on the line today. BMad, Superpowers, SpecKit, raw prompts, and future agent frameworks all plug in as **stage runners**. We don't compete with agent authors; we give them the assembly line, the QA, and the audit trail they don't want to build themselves.

Concretely: the `StageRunner` Protocol is stable; Claude SDK is the shipping implementation; a second implementation is welcome any time a real need appears.

### P-03 — Every run is measurable.

No run exists outside the evaluation system. Every stage emits structured metrics (tokens, cost, duration), every decision point emits structured logs, every output is replayable. If you cannot answer "did this run do better than last week's?" you do not have a2sdlc — you have a chatbot.

### P-04 — Failure is observable, recoverable, and bounded.

Circuit breakers on cost, review cycles, and duration. Retries with structured logs, not silent attempts. A failed run produces a tagged, diagnosable record — not a dangling comment and a confused human. The engine's worst case is *visibly blocked*, not *silently broken*.

### P-05 — Stay small; extend at the edges.

The engine core is small and opinionated. New platforms arrive as adapters. New stages arrive as handlers. New effects arrive as effect-interpreter arms. If a feature needs a rewrite to the core, the feature probably belongs one layer up — in the agent's prompt, in a middleware, or in a separate service.

### P-06 — Real-CI-integration grade, not unit-test grade.

Tests that pass with fake adapters but fail when wired into real GitHub Actions with real tokens, real webhooks, and real timing are a **trust-destroying class of bug**. The engine is a piece of infrastructure; infrastructure that produces silly integration failures loses users faster than one with missing features.

We hold ourselves to: **every release ships only after the full engine runs end-to-end on a real fixture repo in real CI, against real GitHub + real MLflow, with real tokens.** Fake-adapter tests are for velocity, not for trust. Trust is earned in the hot path, on the real platforms, repeatedly.

See architecture vision §13 for the QA strategy this principle requires.

### P-07 — The engine is built by AI agents; every boundary must serve that.

The engine is developed and maintained by AI agents running the engine itself. Every architectural choice — file size, module boundary, naming, import graph — must make it easier for a parallel fleet of agents to edit the code without stepping on each other.

Concrete commitments:
- **One responsibility per file.** 500 LOC hard cap (harness-enforced).
- **Package = the unit of scope.** An agent editing one package reads at most that package + domain.
- **Protocol, impl, tests live in the same package.** No cross-folder archaeology to fix one adapter.
- **No god modules.** The current 500-line `dispatch.py` is the anti-pattern; the target pipeline composition root is ~60 lines.
- **CLAUDE.md per package** describing purpose, what belongs, what does not, how to extend.
- **Stages isolated.** Adding a stage = new file + one dict entry + one transition-table row. No cross-stage edits.
- **Effects additive.** Adding an effect = new Pydantic class + one interpreter arm. No cross-effect edits.

### P-08 — Five-minute onboarding is the adoption gate.

From "team wants to try a2sdlc" to "first merged PR by the engine" must take **under 5 minutes of human effort**. If it takes longer, we lose the team.

The onboarding checklist is a fixed list:
1. Install two GitHub Apps (`a2sdlc-worker`, `a2sdlc-reviewer`) on the target repo.
2. Drop two secrets into the repo (`CLAUDE_CODE_OAUTH_TOKEN`, optional `MLFLOW_TRACKING_URI`).
3. Commit one workflow file (`.github/workflows/a2sdlc.yml`).
4. Commit one config file (`.a2sdlc/config.yaml`) with the default workflow.
5. Label an issue `agent`. Done.

Any new feature that adds a sixth onboarding step is rejected by default. `docs/onboarding.md` is the source of truth.

---

## 6. Positioning

### 6.1 The competitive frame

a2sdlc is **the factory**. Others build the machines, the blueprints, or the observability tooling. We build the assembly line.

| Category | Examples | How a2sdlc differs |
|---|---|---|
| **Agent frameworks (the "machines")** | BMad, Superpowers, SpecKit, LangGraph, CrewAI, AutoGen | Frameworks describe *how* an agent runs a task. a2sdlc drives *when* an agent runs, on which ticket, with what accountability, against what measurement. Frameworks plug in as workers on our line. |
| **Coding agents (episodic)** | Copilot, Cursor, raw Claude, Cody, Aider | Single-turn or session-bound. a2sdlc is ticket-to-merge end-to-end. No overlap — they can run inside our factory as stage-level tools. |
| **AI SDLC platforms (vendor-hosted)** | GitHub Copilot Coding Agent, Sourcegraph Cody PRs, Cognition Devin | Vendor-hosted, single-agent, opaque orchestration. a2sdlc is **self-hosted in your CI**, agent-swappable, with transparent pipeline state and your own tokens. |
| **Workflow engines** | Temporal, Prefect, Airflow, Argo, n8n | General-purpose; require you to assemble the SDLC factory yourself. a2sdlc is the assembled answer — specialized for ticket-driven SDLC. (Temporal is our horizon runtime for the larger-systems edition; see §9.2.) |
| **LLM observability** | Langfuse, Arize, Helicone | Observe calls; don't orchestrate pipelines. a2sdlc uses MLflow natively for the "is this run better than last week's?" question, and observability sinks plug in alongside. |
| **Per-stage point products** | GitHub Copilot reviewer, CodeRabbit, bugbot, Graphite reviewer, Sourcery | Compete at ONE stage only. a2sdlc's stages run **both** as part of the full factory AND as standalone tools (`a2sdlc-review` as a GitHub Action) — so teams can adopt one stage first and graduate to the full line. One architecture, two purchase paths. |

### 6.2 What we are NOT

- Not a closed SaaS. The engine runs in your CI or on your infra.
- Not a "no-code" tool. Configuration is YAML; customization is code.
- Not enterprise-ready today. SSO, SOC2, per-seat billing, RBAC — explicit non-goals per §9.3.
- Not a better single-turn coder than Copilot. Different product category.


---

## 7. Strategic bets

The product will succeed or fail based on these bets. Each should be tested and revisited quarterly.

### Bet #1 — Teams want the pipeline, not the agent.

**Hypothesis:** as agent quality converges across frameworks, teams will care more about **accountable orchestration** than about which framework wrote the code. a2sdlc wins by owning orchestration.

**Invalidation signal:** if agent framework quality diverges drastically (one framework becomes 10× better than others), framework choice dominates and orchestration becomes a detail. We pivot to first-class integration with that framework.

### Bet #2 — Measurable iteration beats vibes.

**Hypothesis:** teams adopting AI SDLC will eventually demand "did this change to the prompt improve outcomes?" and the engine that answers it with numbers wins. MLflow + fixture replay is the differentiator.

**Invalidation signal:** if no team ever runs the evaluation harness after onboarding, the investment is wasted — pivot to a lighter observability layer.

### Bet #3 — Multi-tracker matters.

**Hypothesis:** enterprises and small teams alike refuse to change trackers. GitHub+Jira coexistence is the real world. A GitHub-only tool hits a ceiling early.

**Invalidation signal:** if GitHub-only deployments dominate 12 months in, multi-tracker is architectural debt — simplify to one tracker until demand is proven.

### Bet #4 — Open-core over closed SaaS.

**Hypothesis:** developer-facing tooling adopts faster when it's open, self-hostable, and on the user's own API keys. Closed SaaS coding tools lose to open alternatives once the open alternative reaches parity.

**Invalidation signal:** if open adoption stalls and SaaS clones of a2sdlc grow faster, re-evaluate the business model.

---

## 8. Scope boundaries — what a2sdlc owns vs. what it integrates with

### a2sdlc owns

- The pipeline state machine (stages, transitions, gates, cycles).
- Event ingestion from ticket trackers.
- Session / state / idempotency.
- The effect model (what side-effects happen, in what order, with what audit trail).
- Cost/cycle/duration circuit breakers.
- Evaluation infrastructure (MLflow integration, fixture replay, metric schemas).
- Progress surfacing (comments, logs, subscribers).

### a2sdlc integrates with (does not own)

- **The agent itself** — Claude Agent SDK, Superpowers, BMAD, etc.
- **The tracker** — GitHub Issues, Jira, Linear, etc.
- **The code host** — GitHub, GitLab, ADO.
- **The LLM provider** — Anthropic, OpenAI, Google, LiteLLM.
- **The deploy target** — Dokploy, Vercel, k8s, etc.
- **The observability stack** — MLflow, OTEL, Datadog (sinks).

### a2sdlc explicitly does not own

- Prompts for stages beyond a minimal default set. Teams own their prompts; we provide the scaffolding.
- Code review judgment. The REVIEW stage is configurable; the policy is the team's.
- Deployment decisions. The MERGE stage merges; what happens next is outside scope until DEPLOY stage exists.
- Human-in-the-loop UX. The engine exposes state via tracker comments and labels; UX is the tracker's.
- **Agent memory / project context.** Managed via progressive-disclosure `CLAUDE.md` files in the target repo's `docs/` tree — a convention the Claude Agent SDK already honors via `setting_sources=["project", "local"]`. The engine does nothing special; we document the pattern and stay out of it.
- **Revert flows.** Future `REVERT` stage (reserved slot in architecture §2.27) will handle "label this merged PR for auto-revert" when we get there. Until then, reverts are human-driven.

---

## 9. Scope fence — now, later, not-in-vision

This section is load-bearing. It tells contributors what to build, what to plan for, and what to refuse. Every downstream document (architecture, ADRs, specs) must respect the fence.

### 9.1 Now — the CI edition

**One distribution, running inside the user's CI.** No server, no SaaS, no hosted control plane. "Just git with some stuff." The engine ships as a Python package, installed in a GitHub Actions / GitLab CI job, invoked per ticket event.

| Dimension | Now |
|---|---|
| **Runtime** | The user's CI pipeline (GitHub Actions first, GitLab CI next, local dev always) |
| **Trackers** | GitHub Issues, GitLab Issues, Atlassian Jira, local file |
| **Code hosts** | GitHub, GitLab |
| **State** | Git-native — branch-persisted `state.json`, no external DB |
| **Durability** | CI-job durability (per-event retry). No mid-stage resume. |
| **Identity** | The CI runner's existing tokens (`GITHUB_TOKEN`, `GL_TOKEN`, Jira PAT) |
| **Packaging** | Python package + workflow YAML snippets |
| **Distribution** | OSS (license TBD — see D-02) |

Priority within the "now" scope: **GitHub + GitHub > GitLab + GitLab > Jira + GitHub ≈ Jira + GitLab > local.**

### 9.2 Later — the Temporal edition

**A second distribution, for larger systems**, when the CI edition's constraints (stateless between runs, no mid-stage resume, CI-timeout caps) become binding for real customers.

The Temporal edition shares the same engine core (stage handlers, effects, adapters) but runs as a long-lived service backed by Temporal for durable execution. State lives externally (KV / Postgres). Sessions live externally. Larger workloads, epic orchestration with many children, multi-week runs.

This is **not a migration**; it is a second distribution. CI edition continues to exist for users who want it.

Timing: explored at ~6 months if the CI edition gets traction. See architecture vision H1.

### 9.3 Not in vision — explicit non-goals

The following are out of scope for both editions **until the vision is deliberately revised**:

- **Web UI / admin dashboard.** The tracker IS the UI.
- **Authentication / authorization beyond CI tokens.** No SSO, no per-seat auth, no RBAC.
- **Multi-tenant identity.** Each installation is self-contained in one repo or one dispatcher deployment.
- **Managed SaaS.** No hosted control plane, no billing, no account system.
- **Data retention / GDPR surface.** Inherited from the user's platforms (GitHub, Jira, MLflow).
- **Enterprise procurement posture.** SOC2, pen-test reports, legal reviews — not yet.
- **Closed-source commercial tier.** OSS across the board.

When one of these moves *into* scope, the product vision is updated first, not the architecture.

### 9.4 Closed decisions

| # | Decision | Resolution | Notes |
|---|---|---|---|
| D-01 | Business model | **OSS, two distributions** (CI edition now, Temporal edition later) | Closed 2026-04-22 |
| D-07 | Engine/agent stance | **Factory-of-agents** — swappable workers via `StageRunner` Protocol; Claude-first shipping impl | Closed 2026-04-22 (superseded P-02) |

### 9.5 Still open

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D-02 | **License** | (a) Apache 2.0; (b) MIT; (c) AGPL; (d) BSL with time-based conversion | [DECIDE: @iorlas] — recommend (a) Apache 2.0 for OSS with ecosystem friction minimized |
| D-03 | **Name & home** | (a) yoselabs/a2sdlc; (b) separate org; (c) rename | [DECIDE: @iorlas] |
| D-05 | **First distribution channel** | (a) GitHub Marketplace; (b) direct install docs; (c) content-led (blog + YouTube) | [DECIDE: @iorlas] — (c) probably first, (a) follows |
| D-06 | **Near-term customer target** | (a) 10 design-partner teams; (b) 1000 install-count; (c) one lighthouse customer | [DECIDE: @iorlas] — (a) for signal, (b) for narrative |

---

## 10. Success metrics (north-star candidates)

To be committed in **01a-product-strategy.md** (future document), which expands this one. Candidates:

- **Engine adoption:** repos with `a2sdlc` running in the last 30 days.
- **Pipeline throughput:** median time from `agent` label to `stage:done`, per repo.
- **Human-intervention rate:** fraction of tickets that touch `stage:blocked` or `needs-input` at least once.
- **Cost per ticket:** median USD per merged ticket.
- **Eval signal strength:** number of prompt changes per month where the eval harness gave a green/red verdict with statistical significance.
- **Regression catch rate:** prompt changes reverted due to eval findings / total prompt changes.

---

## 11. Relationship to other documents

| Doc | Expands |
|---|---|
| [`02-architecture-vision.md`](02-architecture-vision.md) | How the engine is shaped to serve this mission over 12–18 months. |
| [`../adr/`](../adr/) | Specific architectural decisions, each traceable back to a principle above. |
| [`../superpowers/specs/`](../superpowers/specs/) | Feature specs; each should open by citing the product principle or bet it serves. |
| `docs/a2sdlc-positioning.pdf` | External-facing version of §6 (positioning). |
| `docs/ai-sdlc-overview.pdf` | External-facing version of §2 (mission) and §4 (winning). |
| `README.md` | Developer-facing onboarding; should link to this doc's §2 and §5. |
