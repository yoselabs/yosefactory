---
title: "<RFC title>"
type: rfc
number: NNNN
status: Draft
owner: "@<owner>"
created: YYYY-MM-DD
updated: YYYY-MM-DD
pitch: "../pitches/YYYY-MM-DD-<slug>.md"
supersedes: null
superseded_by: null
---

# RFC-NNNN: <Title>

## Context

Why are we writing this RFC? What problem does it address? Cite the pitch and any relevant vision documents. A reader coming in cold should understand the landscape in 3 paragraphs or less.

## Goals

Numbered list of what this design must achieve. Each goal should be testable.

1. G1 — …
2. G2 — …

## Non-goals

Numbered list of what this design explicitly does NOT achieve. Prevents scope creep and sets expectations.

1. NG1 — …
2. NG2 — …

## Design

The core of the document. Structure it however the problem demands, but cover:

### Architecture

C4 **container-level** diagram at minimum. Show the moving parts, their responsibilities, and the data flows between them.

### Interfaces

Public APIs, Protocols, wire formats. What changes in how callers interact with the system.

### Data model

New types, modified types, persistence implications.

### Sequencing

If ordering matters (it usually does), describe the sequence of events step by step.

### Error handling

How failures surface, how the system recovers, what's retried, what blocks.

## Alternatives considered

At least 2 alternatives, each with honest trade-offs.

### Alternative A — <name>

- Summary.
- Why we rejected it.

### Alternative B — <name>

- Summary.
- Why we rejected it.

## Trade-offs of the chosen design

What this design costs us, not just what it gives us. Every design has trade-offs; name them explicitly.

## Risks

Specific things that could go wrong, with mitigations.

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| … | Low/Med/High | Low/Med/High | … |

## Rollout

How this ships. Phased? Flag-gated? Migration pathway?

## Test strategy

How we'll know it works. For AI-touching changes, link to the eval plan. State which of the seven QA layers (L1–L7 per architecture vision §13) this RFC's work must pass before ship, and what fixture repos / event corpora it touches.

## Security considerations

Every RFC must address security explicitly — even if the answer is "no new security surface." Cover:
- **Authentication / authorization** — who is allowed to trigger the new behavior, and how is that enforced?
- **Secrets / credentials** — does this touch tokens, API keys, or other secrets? Where do they live, who has access, how are they rotated?
- **Data sensitivity** — does the new behavior read or write sensitive data (issue bodies, code, credentials in diffs)?
- **Third-party surfaces** — new API calls to external platforms? Rate limits, abuse prevention, audit trail.
- **Abuse modes** — can a malicious ticket body, PR diff, or comment cause unintended behavior? Prompt injection, command injection, resource exhaustion.
- **Defaults** — does the default configuration favor safety or convenience?

If the answer to every bullet is truly "no impact," write "No new security surface" and explain why in one sentence. Don't leave this section empty.

## Open questions

Things the RFC does not yet decide. Listed explicitly so reviewers can help close them.

- OQ1 — …
- OQ2 — …

## Decisions extracted

Each decision worth preserving gets its own ADR. List them here as they're written.

- ADR-NNNN: <slug> — …

## Links

- Pitch: [link]
- Related RFCs: …
- Product principles served: …
