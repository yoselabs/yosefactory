# Mode 2 UX Audit — Running Notes

Scratch pad during the test/fix loop kicked off 2026-04-21 post-initial-smoke.
Promoted to a proper handover when the session ends.

## Scenarios

| # | Issue | Shape | Status |
|---|---|---|---|
| #1 | Patient intake CLI | Greenfield scaffold | merged (prior smoke) |
| #2 | `--format json` flag | Extend existing code | in flight |
| #3 | Bugfix (planned) | Fix-in-existing-code | pending |
| #4 | Ambiguous/minimal spec (planned) | Probe spec-stage clarification | pending |

## Observations — Ticket #2 (extend-existing)

### Good

- Label→workflow trigger latency: sub-15s.
- Spec stage completed cleanly in ~6min with a finalized `✅` comment; no mid-stage thrash.
- Concurrency group correctly cancelled the duplicate `issue_comment` run fired by the engine's own ✅ comment (bot-filter + concurrency working together).
- Stage-transition to `stage:implement` routed cleanly into implement stage.
- Live-updating comment during stage shows tool timeline — excellent visibility.

### Confirmed bugs (fixes landed this session)

- `agent` trigger label lingered alongside `stage:implement` after pickup — fixed in `set_stage_label` (also strips `agent`).
- `create_draft_pr` would 422 on retry if an open PR already existed — fixed via `get_pulls(head=owner:branch)` reuse guard.
- JSON log formatter dropped `extra={...}` kwargs — replaced with `_JsonFormatter` that serializes all non-standard LogRecord attrs.

### Open observations (not yet fixed)

- "Agent" row in the live-comment tool timeline shows an empty target column — minor; subagent dispatches don't have a single file/target.
- Second `issues` workflow run fires when engine sets `stage:*` label (this is the state machine re-entering). Still looking for whether this causes thrash on #2 or is handled cleanly by the pipeline's internal state check.
