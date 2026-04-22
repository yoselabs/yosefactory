---
title: "a2sdlc V1.0 scope"
type: rfc
number: 0001
status: Draft
owner: "@iorlas"
created: 2026-04-23
updated: 2026-04-23
pitch: "../pitches/2026-04-23-v1-scope.md"
supersedes: null
superseded_by: null
---

# RFC-0001: a2sdlc V1.0 scope

## Context

The vision chain (product vision, architecture vision, design process) was
settled 2026-04-22 and describes 12–18 months of engine evolution. Nothing
ships until scope is cut. This RFC is the formal companion to
[`../pitches/2026-04-23-v1-scope.md`](../pitches/2026-04-23-v1-scope.md): it
records the per-commitment, per-phase, per-stage decisions for V1.0, and
explains why each is IN or POSTPONED.

V1.0 is **the first shippable cut** that earns engineering trust on one real
repo (the `iorlas/a2sdlc-smoke` fixture that already backs the GH adapter
integration tier). All engine refactor work happens on a dedicated branch in
`a2sdlc-engine`; the engine runs end-to-end against `a2sdlc-smoke`. It is not
the full vision; it is the minimum viable slice of the target architecture on
the hot path (GitHub + GitHub, Mode 2, 4 stages, N1/N7/N8/interim-N9).

**V1.0 is private-only**, not a public release. Public release (Marketplace
listing, public-repo adoption, external install push) happens post-V1.0,
after full N9 hardening.

Architecture commitments closed in the vision (five patterns on hexagonal-lite,
12 bounded-context packages, three load-bearing types, declarative workflow
YAML, MLflow idiomatic usage, effects transient per Q2, `StageRunner` Protocol
stable per Q4) are **not reopened** here. This RFC commits scope, not shape.

## Goals

1. **G1** — Name every near-term commitment, migration phase, supported stage,
   supported tracker, quality gate, and observability sink as IN or POSTPONED
   for V1.0.
2. **G2** — Give one-paragraph rationale for every IN and every POSTPONED
   decision, so a future contributor can reconstruct the reasoning without
   rereading the whole vision chain.
3. **G3** — Declare which of the seven QA layers (L1–L7 per architecture
   vision §13) are required before V1.0 can tag a release.
4. **G4** — Declare the interim security posture for the N9 window (ADR-0006
   drafted but not fully implemented).
5. **G5** — Stay consistent with the solo-dev override in the design process
   (§4): Pitch + RFC at team size 1 is enough; this RFC does the RFC's job
   because cross-package contracts change (new Protocols, new `Effect` ADT,
   `CompositionProfile` wire shape).

## Non-goals

1. **NG1** — Re-litigating architecture. The five patterns, twelve packages,
   three types, and effects-transient decision stand.
2. **NG2** — Deciding the full post-V1.0 roadmap. POSTPONED items get
   trigger-for-revisit notes, not ship dates.
3. **NG3** — Writing the phase-by-phase implementation plan. That belongs in a
   `docs/superpowers/specs/` document derived from this RFC, per design process
   step (4).
4. **NG4** — Fixing business-model / license / name open questions
   (D-02, D-03, D-05, D-06 in product vision §9.5). Orthogonal to scope.
5. **NG5** — Closing ADR-0006 attacker model in full. This RFC commits to the
   interim posture; ADR-0006 is the downstream deliverable.

## Design

### Architecture

V1.0 does not introduce new architecture — it is the **target shape from
`02-architecture-vision.md` §7** applied on the GitHub+GitHub hot path. No
new packages beyond the 12 named there. No new load-bearing types beyond
`Event`, `StageHandler`, `Effect`.

Container-level shape for V1.0:

```
                ┌────────────────────────────────────┐
                │ GitHub repo (iorlas/a2sdlc-smoke)  │
                │ issues / labels / PRs / protection │
                └─────────────┬──────────────────────┘
                              │ webhook
                              ▼
                ┌────────────────────────────────────┐
                │ GitHub Actions workflow            │
                │ .github/workflows/a2sdlc.yml       │
                └─────────────┬──────────────────────┘
                              │ invokes
                              ▼
             ┌──────────────────────────────────────────┐
             │ a2sdlc engine (CI edition)               │
             │ ┌──────────────────────────────────────┐ │
             │ │ pipeline.py (≤ 80 LOC)               │ │
             │ └─────────────┬────────────────────────┘ │
             │  ingress / gating / session / agent      │
             │   stages (SPEC, IMPLEMENT, REVIEW, MERGE)│
             │    effects + interpreter                 │
             │     middleware onion                     │
             │      observability (progress, MLflow)    │
             └──────┬─────────────────────┬─────────────┘
                    │                     │
                    ▼                     ▼
           ┌─────────────────┐   ┌────────────────────┐
           │ GitHub Apps     │   │ MLflow tracking    │
           │ worker+reviewer │   │ (optional per repo)│
           └─────────────────┘   └────────────────────┘
```

### Interfaces

V1.0 locks the following Protocols (they may gain impls post-V1.0, but the
shapes are stable):

- `StageHandler` (from §7.2): `preconditions`, `execute`, `effects`.
- `Effect` sum type (§7.2) with V1.0 arms only — see §Data model below.
- `WorkAdapter` + `ReviewAdapter` + `GitAdapter` (existing).
- `StateStorage` (per ADR-0005) — `GitFileStateStorage` the only V1.0 impl.
- `SessionStorage` (new in P2 per Q7) — `LocalDiskSessionStorage` the only
  V1.0 impl.
- `StageRunner` (Q4 closed) — Claude SDK the only V1.0 impl.
- `CompositionProfile` (P6) — slots for `tracker`, `ingress`, `review`, `git`,
  `progress`, `middleware`. V1.0 ships one profile combination: GitHub-tracker
  + GitHub-event-path-ingress + GitHub-review + local-git + [gh_comment,
  mlflow, gh_actions_log, rich_console] + [idempotency, retry, logging,
  telemetry].

### Data model

`TicketState` schema_version 2 per ADR-0005 lands in P1. Parent/child fields
exist but stay empty — N2 is POSTPONED so no orchestrator writes them.

V1.0 `Effect` arms (everything else in the architecture vision §7.2 catalog is
POSTPONED):

- Session lifecycle: `StateWrite`, `CommentStart`, `CommentFinalize`,
  `CreateDraftPR`, `UpdatePR`, `MergePR`, `PostReview`, `PostInlineReview`
  (N1), `SetCurrentStage`, `MarkBlocked`, `MarkDone`, `MarkNeedsInput`.
- Git: `CommitAndPush`, `CleanupBase`.
- Control flow: `Transition`.
- Quality / eval: `RunQualityGate`, `RunSecretsScan` (N4 partial),
  `LogMetric`, `LogArtifact`.

Not in V1.0: `NotifySlack`, `CreateChildTicket`, `TriggerSpecRefresh`,
`SplitChildTicket`, `CancelChild`, `RateLimitDeferred`, `CancelRunningJobs`,
`RunDependencyAudit`, `RunSemgrep`, `CheckLicensePolicy`, `CleanupWorktree`.

### Sequencing

Migration phase order is the order from architecture vision §10 (P1 → P8).
N-items land within phases: N1 with P2, N8 with P6, interim N9 (ADR-0006
drafted) any time after P3, N7 QA layers retrofitted against phases per §13.4.

No work on POSTPONED items blocks V1.0 ship. POSTPONED items MAY get
architectural seams landing in V1.0 if the seam costs ≤ 1 day and removes
a future retrofit risk (e.g. `SessionStorage` Protocol from Q7).

### Error handling

Unchanged from vision. Four error-shape effects collapse into interpreter arms
(P3). Branch-protection rejection on MERGE falls back to "PR ready, awaiting
human merge" (Q12 closed as part of N8).

## Scope matrix

Single authoritative table. **IN** = required for V1.0 ship. **POSTPONED** =
explicitly out of V1.0, but still in the vision (post-V1.0 work).

### Near-term commitments

| # | Commitment | Decision | Rationale (one line) |
|---|---|---|---|
| N1 | Inline PR code review | **IN** | Without line-level comments, REVIEW is a wall of text, not a product. Lands with P2. |
| N2 | Subtask-driven execution | **POSTPONED** | Biggest single N-item; hierarchical branches + orchestrator stage = scope explosion. Schema placeholders land in P1 only. |
| N3 | Worktree-isolated local execution | **POSTPONED** | Local is tracker-priority #3; `run_id` already isolates parallel A/B. Nice-to-have. |
| N4 | Security-in-every-stage | **PARTIAL IN** | Only `RunSecretsScan` (gitleaks) effect + interpreter arm. Full shift-left across stages POSTPONED. |
| N5 | Backpropagation / adaptive planning | **POSTPONED** | RFC-blocked and depends on N2. N2 is POSTPONED, so N5 is automatic. |
| N6 | Standalone stage execution (architecture vision §2.21a — every stage invokable on its own) | **SPLIT, with one CLI promoted** | **Architectural side IN** (P2): handlers don't assume prior-stage on-disk artifacts; effects interpreter supports standalone mode. Free. **`a2sdlc review <pr-url>` CLI IN** (~1 day on top of P2): exercises the constraint once with a real command so it doesn't rot, and delivers the standalone review command we'll need soon. **`a2sdlc spec`, `a2sdlc implement`, per-stage GitHub Actions packaging POSTPONED** (marketing surface, no V1.0 trust value). |
| N7 | Robust QA strategy (7 layers) | **PARTIAL IN** | L1–L6 **IN** against one fixture repo. L7 eval harness scaffolded + one-stage pilot; full L7 coverage **POSTPONED**. See §Test strategy. |
| N8 | Two GitHub Apps + credential profiles | **IN** | Onboarding doc already depends on this (P-08). Without it, engine self-approves — brittle under branch protection. Closes Q12. |
| N9 | Attacker model (ADR-0006) | **INTERIM** | ADR-0006 **drafted and Accepted** with: attacker model, tool allowlists per stage, delimiter escaping, effect-level gating on merge/label. V1.0 is private-only so public-repo exposure is not in scope. Full hardening **POSTPONED** as a pre-public-release blocker. |

### Trackers / code hosts (priority order from product vision §9.1)

| Combination | Decision | Rationale |
|---|---|---|
| GitHub Issues + GitHub repo | **IN (tested to L6)** | The hot path. Priority #1. Must remain green at every phase boundary. |
| Local file + local git | **IN (dev loop only)** | Developer loop / dogfood; already works. No regression budget. |
| Jira + GitHub repo (dispatcher path) | **SCAFFOLDED, NOT TESTED** | Dispatcher bounded context + Jira `WorkAdapter` + `workflow_input` ingress + `dispatcher_http` output subscriber all survive the refactor and compile green. Exercised at L1/L2 (unit + contract) only — NOT at L4 (real Jira sandbox) or L6 (end-to-end). Full Jira testing + dispatcher hardening lives in a separate follow-on effort with its own fixture and success signal. |
| GitLab Issues + GitLab repo | **POSTPONED** | Ships in the next version. Adapter Protocol stays; no shipping impl. |
| Jira + GitLab repo | **POSTPONED** | Combinatorial — blocks on GitLab adapter. |
| Linear / ADO / Forgejo / Bitbucket | **NOT IN VISION (V1.0)** | Adapter slots reserved; no commitment. |

### Migration phases

| Phase | Decision | Rationale |
|---|---|---|
| P1 — Model the domain | **IN** | Event ADT, `ResolvedConfig`, `BlockReason`, TicketState v2 per ADR-0005. Blocks everything else. |
| P2 — Stage handlers | **IN** | Largest decay-reversal phase; MERGE becomes a regular handler; N1 lands here; N6 constraint enforced here. |
| P3 — Effects ADT + interpreter | **IN** | Collapses copy-pasted error blocks; unlocks eval replay; N4 secrets-scan effect lands here. |
| P4 — Pipe-and-filter dispatch | **IN** | The whole point — `pipeline.py` ≤ 80 LOC is a V1.0 success criterion. |
| P5 — Middleware layer | **IN** | Idempotency middleware is load-bearing for L3 concurrency tests (per N7). Kills double telemetry framing. |
| P6 — Unified composition | **IN** | Required for N8 (credential profiles wire through `CompositionProfile`). Kills Mode 1/Mode 2 env-branching. |
| P7 — Rename & relocate | **IN** | 1 day per vision §10. Cheap closure; enables P8 linter. |
| P8 — Lock the shape | **IN** | Import-linter + architecture tests + release gate wiring to L6 smoke. Without P8, trust is aspirational. |

### Stages

| Stage | Decision | Rationale |
|---|---|---|
| SPEC | **IN** | Existing. Becomes a `StageHandler` in P2. |
| IMPLEMENT | **IN** | Existing. Becomes a `StageHandler` in P2. Gets `RunSecretsScan` effect (partial N4). |
| REVIEW | **IN** | Existing. Gets `PostInlineReview` effect (N1). Credential profile = reviewer App (N8). |
| MERGE | **IN** | Existing. Becomes a regular handler (stops being special-cased). Q12 fallback. |
| DEPLOY | **POSTPONED** | No customer asking. Out of scope per product vision §8. |
| STALENESS_CHECK | **POSTPONED** | No production fleet yet to be stale against. |
| EPIC_SHAPING | **POSTPONED** | Upstream of N2 which is POSTPONED. |
| RELEASE_NOTES | **POSTPONED** | Nice-to-have. Not on the trust path. |
| SECURITY_SCAN stage | **POSTPONED** | Replaced for V1.0 by cross-cutting `RunSecretsScan` effect (partial N4). |
| REVERT | **POSTPONED** | Reserved slot per §2.27. No fleet means no revert urgency. |

### Quality gates

| Gate | Decision | Rationale |
|---|---|---|
| `make check` post-IMPLEMENT | **IN** | Already exists. `RunQualityGate` effect wraps it. |
| Diff-coverage threshold | **IN** | `make coverage-diff` is already part of `make check` per project CLAUDE.md. Free. |
| Secrets scan (gitleaks) | **IN** | Single effect + interpreter arm. High trust value, cheap. |
| Trivy (container / dep CVEs) | **POSTPONED** | Effect variant may be registered for forward-compat; no interpreter arm. |
| Semgrep (SAST rules) | **POSTPONED** | Same — registered, not wired. |
| License policy | **POSTPONED** | Enterprise procurement concern, not V1.0. |

### Observability sinks

| Sink | Decision | Rationale |
|---|---|---|
| MLflow | **IN** | Bet #2 differentiator. Already integrated; preserved through middleware refactor. |
| Ticket progress comment | **IN** | Primary user-facing UX; the tracker IS the UI (vision §6.2). |
| GH Actions log (agent-prefixed per §2.22) | **IN** | Already works — agent prefix format lands cheaply in P2/P3. |
| Rich console (local dev) | **IN** | Already works; zero cost to preserve. |
| Dispatcher HTTP subscriber | **POSTPONED** | Jira is POSTPONED, so the dispatcher bridge is unused. |
| OpenTelemetry / Datadog / web UI | **POSTPONED** | No current consumer. Slot-fits when needed. |

## Per-item rationale (required-for-V1.0-trust)

### Why N1 is IN

Inline PR review is the distinguishing product UX for REVIEW. Reviewers compare
a2sdlc output against CodeRabbit / Copilot reviewer / bugbot output, all of
which post line-level comments. A single aggregate comment fails the
face-validity test on first contact.

### Why N4 is PARTIAL IN (secrets scan only)

Secrets scanning is a one-effect, one-interpreter-arm commitment that catches
the most damaging class of AI-introduced regressions (credentials leaked into
code the engine wrote). Trivy / semgrep / license policy are multiplicative
scope — each needs configuration surface and per-repo tuning. V1.0 earns trust
on "the engine does not leak your secrets"; it does not promise full
shift-left security.

### Why N6 is SPLIT, with `a2sdlc review` promoted

The **architectural** side of N6 (handlers don't assume prior-stage side
effects on disk; effects interpreter supports a standalone mode) is enforced
in P2 anyway as a property of the target shape — it's free.

The **product** side of N6 (per-stage CLIs + per-stage GitHub Actions) is a
marketing surface with no V1.0 trust value — but one CLI is worth promoting:
**`a2sdlc review <pr-url>`**. Two reasons: (a) **tech-debt risk** — an
architectural constraint that is never exercised by a real end-to-end command
rots within months; L2 contract tests assert shape, not that a real CLI
actually drives a real REVIEW against a real PR. (b) the command is already
needed operationally soon after V1.0 ships, so building it as part of V1.0 is
amortized on top of P2 for roughly one additional day. The other stages'
standalone CLIs + per-stage GitHub Actions remain POSTPONED.

### Why N7 is PARTIAL IN (L1–L6 on, L7 pilot)

L1–L6 answer "does the engine **code** work end-to-end on real platforms with
real tokens?" That is the P-06 question V1.0 must answer affirmatively. L7
answers a different question: "is this **prompt / stage-runner** producing
better outputs than last week's?" — that is about **stage output quality**
(e.g. SPEC document completeness, REVIEW finding relevance), measured by eval
metrics against fixture tickets. L7 does NOT measure engine code correctness;
L1–L6 do. L7 is the Bet #2 differentiator and matters for long-term
iteration, but it is not a V1.0 trust blocker. Scaffolding L7 + piloting on
one stage (SPEC) proves the harness shape without committing to corpus
construction across all stages.

### Why N8 is IN

The onboarding doc (`docs/onboarding.md`, driving P-08) already names both
Apps in step 1. Either N8 is IN, or the onboarding doc needs to be rewritten
with a self-approval workaround — which is brittle against branch protection
(Q12). N8 also forces `CompositionProfile.credential_profile` to exist, which
is P6's natural shape. The dependencies all point the same direction.

### Why N9 is INTERIM

Public-repo deployments require full prompt-injection defense. **V1.0 is
private-only**, so public-repo exposure is not a V1.0 concern. Interim
protection (tool allowlists per stage, delimiter escaping, merge/label effect
gating) is enough for the private-rollout trust target. Full hardening is a
**pre-public-release blocker** — it ships in the post-V1.0 pitch that
precedes the first public Marketplace listing, not in V1.0 itself.

## Per-POSTPONED rationale (what triggers revisit)

| POSTPONED item | Trigger to revisit |
|---|---|
| N2 subtasks | First epic with 3+ children that a human would obviously want auto-orchestrated, **and** V1.0 has been in green production for 4+ weeks. |
| N3 worktrees | First concurrent-local-agent collision (two runs stomp on one another's working tree). Denis's parallel A/B runs today don't hit this because `run_id` isolation is file-level, not tree-level. Revisit if that changes. |
| N5 backpropagation | Blocks on N2. Won't revisit before N2. |
| N6 `a2sdlc spec` / `a2sdlc implement` CLIs + per-stage GitHub Actions | `a2sdlc review` ships in V1.0 and exercises the architectural constraint. The other CLIs and the GH Action packaging revisit on first design-partner ask. |
| GitLab adapter | First design-partner GitLab team. Product vision Bet #3 — multi-tracker matters — but invalidation signal is also live: if GitHub-only dominates at 12 months, pivot (§Bet #3 invalidation). |
| Jira + dispatcher | First design-partner Jira team. Dispatcher is a separate bounded context — revisit triggers a dispatcher pitch. |
| DEPLOY / REVERT stages | First production fleet adopts a2sdlc and asks for it. |
| STALENESS_CHECK | When stale agent branches start causing operational pain. |
| Subagents (pen-tester, performance-reviewer) | When N4 expands beyond secrets scan OR when REVIEW quality metrics plateau and subagent-specialization is the natural next move. |
| Rate-limit park-and-sweep | First repo hits the rate-limit ceiling. |
| OTEL / Datadog / web UI sinks | First user with a serious observability stack asks. |

## Dispatcher architecture — no revision, one ADR

The dispatcher (`packages/dispatcher/`) does **not** need architectural
revision for V1.0. The vision §7.6 already specifies it as a separate bounded
context from the engine with a thin wire protocol:

- **Input surface:** `WorkflowInputReader` — the engine reads ticket events
  delivered by the dispatcher as workflow input on the CI runner.
- **Output surface:** HTTP POST `/runs/{id}/events` — the engine publishes
  progress events back to the dispatcher via `DispatcherEventSubscriber`.

P1–P8 change how the **engine** selects the Jira/dispatcher mode — P6's
`CompositionProfile` replaces the `DISPATCHER_URL` env-branch with
`profile.ingress = "workflow_input"` + `profile.progress += ["dispatcher_http"]`
— but that's engine-side only. Dispatcher-side code (HTTP receive, Jira event
translation, runs table) is untouched.

The only dispatcher-adjacent deliverable in V1.0 is **ADR-0007 —
engine/dispatcher wire protocol**, which formalizes the two surfaces above
and closes vision-Q1 ("dispatcher as a formal bounded context"). Without that
ADR, the Jira scaffolding has no contract to test against in the follow-on
effort. ADR-0007 is ~1 page of Nygard-style text, not an RFC.

**Doc hygiene note:** architecture vision §12.2 Q1 references writing
"ADR-0005" for this decision, but ADR-0005 is already taken by TicketState.
The dispatcher ADR is renumbered to ADR-0007 here and in the extracted-ADR
list below. A follow-up pass on the architecture vision should correct the
stale ADR number — not a V1.0 blocker.

## Alternatives considered

### Alternative A — "P1+P2+P3 only" minimal V1.0

Architecture vision §10 notes that P1–P3 alone deliver ~80% of the value.
V1.0 could be "ship the three big refactor phases, leave P4–P8 for later."

Rejected: without P4 (pipe-and-filter dispatch), the 500-LOC `dispatch.py`
survives V1.0 — violating P-07's 500-LOC cap on the most-imported file. Without
P6 (unified composition), N8 can't cleanly plumb credential profiles and the
`DISPATCHER_URL` env-branch remains. Without P8 (import-linter lockdown), the
new shape erodes within weeks — architectural decay unchecked (§3 all over
again). P4–P6 + P8 are cheap (≤ 1 day each per §10) and each removes a
known-bad leak. Cutting them buys 4–5 days and shrinks the trust surface by a
lot more.

### Alternative B — "include N2 for the epic story"

N2 is the most product-visible N-item (shaping agent fans out to children is
the demo everyone wants). Including it would give V1.0 a splashier launch
narrative.

Rejected: N2 is the biggest single piece (its own ADR per architecture vision
§11 near-term commentary). Including it breaks the 4–6 week appetite. V1.0 is
about earning trust on single-ticket flows; N2 is the second unit of trust.
Ship single-ticket first, N2 second.

### Alternative C — "cut N1 (inline review) too, ship bare minimum"

Pure refactor V1.0: migrate to target architecture, keep existing REVIEW
behavior (aggregate comment). Smaller surface, faster ship.

Rejected: P-06 ("real-CI-integration grade, not unit-test grade") implies the
product must look credible at first contact. An aggregate-comment REVIEW does
not look credible next to Copilot reviewer. N1 is small (one `Effect` variant
+ one adapter method) and the value is outsized. Cutting it saves days,
damages the trust signal for weeks.

## Trade-offs of the chosen design

**Cost 1 — Partial tracker diversity signal.** V1.0 proves a2sdlc works on
GitHub. The Jira dispatcher path is scaffolded at L1/L2 (compiles, contracts
hold) but not tested at L4/L6 — so Jira regressions in non-adapter layers
are possible and only caught in the Jira follow-on effort. GitLab stays
entirely untested. Bet #3 (multi-tracker matters) gets partial evidence from
V1.0, full evidence post-V1.0.

**Cost 2 — Dogfood-only trust.** The fixture repo is not an external customer.
"Works on iorlas/a2sdlc-smoke" is weaker evidence than "works on three real
customer repos." V1.0 earns engineering trust, not product-market trust.

**Cost 3 — Security posture is interim, not final.** V1.0 is private-only —
no public-repo exposure, so the interim posture is acceptable for the V1.0
window. The real cost: V1.0 ship does NOT unlock public release. The pitch
that hardens N9 fully must ship before any public Marketplace listing.

**Cost 4 — Eval harness is scaffolded, not production.** L7 pilot on one stage
doesn't validate Bet #2 at scale. Prompt iteration without numbers continues
for a while longer than feels comfortable.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Migration creep — P1–P8 grows to 10 weeks | Medium | High | Hard rule: each phase ships green; no drive-by refactors. RFC-0001 is the scope fence. |
| N7 L4 (real-platform) flakes on rate limits | Medium | Medium | L4 runs nightly, not per-push; cassettes cover the common paths per CLAUDE.md "GH adapter integration tier." |
| N9 interim posture misjudged — prompt injection in the wild | Low | High | Docs mark public-repo use experimental; no marketing for public-repo use in V1.0 window. ADR-0006 drafted pre-ship. |
| N8 branch-protection edge cases (Q12) | Medium | Medium | Fallback to "PR ready, awaiting human merge" is explicit in-scope; test at L4. |
| Claude SDK breaking change lands mid-migration | Low | High | `StageRunner` Protocol stable means the impl is swappable; pin SDK version during migration window. |
| Fixture repo state drifts and L6 smoke starts failing for non-engine reasons | Medium | Low | Fixture repo has its own lightweight ownership; smoke failures investigated same day they happen. |
| 4–6 week appetite blows out | Medium | Medium | Nice-to-haves (pitch §Nice-to-haves) get cut in the documented order. |

## Rollout

Phased per architecture vision §10 — P1 → P8 sequentially. Each phase is
shippable and green; the main branch never contains a half-finished phase.
Near-term items land within phases:

- N1 with P2 (`StageHandler` for REVIEW returns structured payload + inline
  comments effect).
- N4 partial with P3 (`RunSecretsScan` effect + interpreter arm).
- N8 with P6 (`CompositionProfile.credential_profile` + two-App token fetch).
- N7 layers retrofitted against phases per §13.4.
- N9 interim (ADR-0006) can land any time after P3; recommend immediately
  before P8 release gate goes live.

V1.0 tag happens when all nine success signals from the pitch §Success signal
are green. No earlier.

## Test strategy

Mapped to the seven QA layers from architecture vision §13:

| Layer | V1.0 requirement |
|---|---|
| **L1 — Unit** | **Required.** Every new ADT arm, every effect-interpreter arm, every pure function in `ingress/`, `gating/`, `session/`. Existing coverage preserved — no regressions. |
| **L2 — Contract** | **Required.** Fake adapters and real adapters share one conformance suite. `StateStorage`, `SessionStorage` (new in P2 per Q7), `WorkAdapter`, `ReviewAdapter`, `GitAdapter`, `StageRunner`. `TicketState` schema invariants (I1–I8 per ADR-0005) covered. |
| **L3 — Integration (fakes)** | **Required.** Full dispatch flow with fake adapters. Concurrency tests (two dispatches same ticket). Chaos tests (adapter fails N% with retryable errors). |
| **L4 — Real-platform** | **Required on GitHub only.** Nightly CI run against `iorlas/a2sdlc-smoke` using real App installation tokens. Cassette replay on every push (already active per CLAUDE.md GH adapter integration tier). Jira L4 **deferred to Jira follow-on** (dispatcher is scaffolded at L1/L2 only in V1.0). GitLab L4 **POSTPONED** with the adapter. |
| **L5 — Event replay** | **Required.** Corpus seeded with real payloads for: `issues.labeled`, `issue_comment`, `pull_request.labeled`, `pull_request_review.submitted`, `pull_request_review_comment`, `issues.closed`. Other trackers POSTPONED. |
| **L6 — End-to-end smoke on real CI** | **Required as release gate.** The ten-cycles-clean success signal from the pitch is enforced here. Tag cannot move without smoke green. |
| **L7 — Eval harness** | **Scaffolded + piloted on one stage (SPEC).** Full L7 coverage POSTPONED. MLflow integration already exists; eval plan template per design process step (5) drives the pilot. |

Contract conformance (per §13.3) is non-negotiable: if a fake passes a test
the real fails (or vice versa), the fake is wrong — fix the fake, don't skip.

Token-matrix coverage for V1.0: `ghs_` installation tokens (both Apps) +
`secrets.GITHUB_TOKEN` fallback. `ghp_` PATs and GitLab token types POSTPONED
with their adapters.

Release gate from P8 onward: tag cannot move without L1–L6 green against the
V1.0 scope. L7 pilot green is a soft gate (blocks release if it regresses by
> 10% on the pilot stage) — tune the threshold from the first pilot run.

## Security considerations

**Authentication / authorization.** V1.0 uses two GitHub Apps (N8) — worker
and reviewer — with distinct installation tokens per stage per
`CompositionProfile.credential_profile`. Tokens live in CI secrets, not in
code. Onboarding doc already enforces this.

**Secrets / credentials.** `CLAUDE_CODE_OAUTH_TOKEN` and optional
`MLFLOW_TRACKING_URI` are the only non-App secrets. Cassette scrubber
(`tests/integration/adapters/conftest.py` per CLAUDE.md) strips `authorization`
headers before cassettes hit disk — invariant. `agent-harness security-audit`
runs on every push; `agent-harness security-audit-history` runs once at
bootstrap.

**Data sensitivity.** The agent reads ticket bodies, comments, diffs, code.
All of that content is already in the user's GitHub — a2sdlc does not expand
the surface. MLflow tracking URI may be self-hosted; users who pipe runs to a
third-party MLflow accept that surface.

**Third-party surfaces.** GitHub (both Apps), Anthropic (Claude API), MLflow
(optional). No other new external API calls in V1.0.

**Abuse modes.** This is the N9 window. V1.0 interim posture:

1. **Tool allowlists per stage.** SPEC and REVIEW do not have `Write` or
   `Edit`; only IMPLEMENT does. MERGE has deterministic git/PR operations via
   the effects interpreter, not agent-issued tool calls. Prevents the "review
   stage writes malicious code" vector.
2. **Delimiter escaping for untrusted input.** Ticket bodies, comments, diffs
   get wrapped in clearly-demarcated blocks in the prompt so the agent treats
   them as data, not instruction.
3. **Effect-level gating.** `MergePR` and `PostReview` effects are applied
   only when their originating handler's preconditions + gating accepted the
   event. Label-flip vector is mitigated by idempotency middleware + gating.
4. **`RunSecretsScan` on IMPLEMENT output.** Catches the obvious "agent
   committed a credential" regression.

Interim posture is NOT full defense. Public-repo deployments must be marked
**experimental** in docs until full ADR-0006 ships (post-V1.0). Private-repo
deployments with trusted ticket authors are the V1.0 target.

**Defaults.** V1.0 defaults favor safety: branch protection assumed on
`main`; reviewer App is a distinct identity; no self-approval; no merge
without passing `make check`; secrets scan enforced pre-merge. Convenience
features (skip gates, auto-merge without review) POSTPONED.

## Open questions

- **OQ1** — Exact pilot stage for L7 eval harness. Recommendation: SPEC
  (smallest fixture corpus, most prompt-churn). Confirmable by human.
- **OQ2** — Fixture repo branch protection specifics. Does iorlas/a2sdlc-smoke
  currently enforce the same rules we'll require of first external adopters?
  If not, configure before P8.
- **OQ3** — Does N3 worktree isolation need to land earlier if Denis's
  parallel A/B runs collide during the P1–P8 migration window? No collision
  today; flag if it changes.
- **OQ4** — ADR-0006's three defense layers are stated above. Is that the
  complete interim posture, or is there a fourth layer (e.g., output filtering
  before `CommentFinalize`)? Owner to confirm when drafting ADR-0006.
- **OQ5** — L7 pilot pass criterion. L7 measures **SPEC stage output
  quality** (not engine code correctness). Recommendation: if the pilot
  metric (e.g. spec-completeness against fixture tickets) regresses by more
  than a configured threshold between two engine versions, block the release.
  Start at 10% and tune after the first pilot run produces baseline noise
  numbers. Engine code regressions are L1–L6's job.

## Decisions extracted

The following ADRs will land alongside V1.0 implementation:

- **ADR-0006** — Attacker model and trust boundaries (N9 interim posture
  formalization).
- **ADR-0007** — Engine/dispatcher wire protocol (closes vision-Q1;
  formalizes `WorkflowInputReader` + `/runs/{id}/events` as the only two
  surfaces between engine and dispatcher). Prerequisite for the Jira
  follow-on effort.
- **ADR-0008** — V1.0 release engineering — tag discipline, L6 smoke gate,
  the nine-success-signal checklist.

Existing ADRs referenced: ADR-0001 hexagonal-lite, ADR-0003 evaluation not
telemetry, ADR-0004 import-linter, ADR-0005 TicketState schema.

## Links

- Pitch: [../pitches/2026-04-23-v1-scope.md](../pitches/2026-04-23-v1-scope.md)
- Product vision: [../vision/01-product-vision.md](../vision/01-product-vision.md)
- Architecture vision: [../vision/02-architecture-vision.md](../vision/02-architecture-vision.md)
- Design process: [../vision/03-design-process.md](../vision/03-design-process.md)
- ADR-0005: [../adr/0005-ticket-state-schema-and-storage-invariants.md](../adr/0005-ticket-state-schema-and-storage-invariants.md)
- Onboarding: [../onboarding.md](../onboarding.md)
- Related RFCs: none yet (this is RFC-0001)
- Product principles served: P-01 (humans decide), P-02 (factory owns the
  line), P-03 (every run is measurable — via L7 pilot), P-04 (failure is
  observable), P-05 (stay small), P-06 (real-CI-integration grade), P-07
  (built by agents for agents — 500 LOC + thin composition root), P-08
  (5-minute onboarding).
