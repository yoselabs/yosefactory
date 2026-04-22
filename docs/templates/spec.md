---
title: "<Spec title>"
type: spec
status: Draft
owner: "@<owner>"
created: YYYY-MM-DD
updated: YYYY-MM-DD
rfc: null
pitch: null
author:
  human: null
  agent: null
---

# <Spec title>

## Goal

One or two sentences: what this spec will produce and why.

## Non-goals

What this spec explicitly will NOT do.

## Plan

Step-by-step implementation plan. Each step:
- Small enough to land as one commit.
- Written as a test-first pair (TDD): "add failing test for X" → "implement X".
- Has a clear done criterion.

1. **Step 1** — …
2. **Step 2** — …

## File-level changes

| File | Change |
|---|---|
| `path/to/file.py` | New — describes X |
| `path/to/other.py` | Modified — adds Y |

## Test strategy

Map this spec's work onto the seven QA layers (L1–L7 per architecture vision §13). For each layer that applies, name what this spec contributes.

- **L1 Unit** — …
- **L2 Contract** — …
- **L3 Integration (fakes)** — …
- **L4 Real-platform** — … (which fixture repo / sandbox?)
- **L5 Event replay** — … (new event payloads added to corpus?)
- **L6 E2E smoke** — … (does the smoke workflow need updating?)
- **L7 Eval** — … (AI-touching? link to eval plan)

## Security considerations

- **Tokens / secrets touched:** …
- **New external API calls:** …
- **Data sensitivity:** …
- **Abuse modes / input-trust assumptions:** …

If no new security surface, write "No new security surface" and explain in one sentence.

## Rollout

Is this feature-flagged? Migrated incrementally? Anything to watch on deploy?

## Backout

How to revert if this goes wrong. If not revertible, name that explicitly.

## Links

- RFC: [link]
- Pitch: [link]
- Eval plan: [link, if applicable]
