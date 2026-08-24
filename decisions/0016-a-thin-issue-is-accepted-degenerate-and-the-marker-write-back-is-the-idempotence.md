# ADR-0016 — a thin issue is accepted with a degenerate frame; the marker write-back, not a cache, is the create idempotence mechanism

**Status:** Accepted
**Date:** 2026-08-24
**Supersedes:** —
**Superseded by:** —
**Revisit trigger:** of the first thirty items ingested via `create`, if more than half sit
unclaimed past their first eligible turn specifically because `frame.method` is the placeholder
string — that would mean the degenerate frame is not merely loose (S1019's expected cost) but
actively blocking work, and the "no rigorizer here" boundary needs revisiting. Also revisit if
`ingest()` is ever called concurrently against the same repository — the marker write-back closes
the double-ingest window for a single-caller `ingest()`, not for two overlapping ones (design.md,
"what this does not attempt").

## Context

[[D031]] adds `create` as a fourth board intent command: an issue opened on the tracker, with no
item marker, becomes a backlog item. Two build-time choices were left to this change, neither
settled by D031 itself:

1. **What does `create` do with a thin issue** — a title and little or no body — given
   `backlog.ITEM`'s `created` rule requires non-empty `goal`, `method`, `assumptions` (D019)?
2. **How is double-ingest structurally prevented**, given D031's own accepted window between an
   issue opening and `ingest()` running?

## Decision

**(1) Accept a thin issue with a mechanically-built degenerate frame.** `goal` = issue title,
`method` = issue body or a fixed placeholder string if empty, `assumptions` = a fixed literal
stating the frame was never rigorized. No refusal, no blocking question. Rejected alternatives and
why, in `openspec/changes/open-issue-becomes-backlog-item/design.md` ("the thin-issue choice") —
refusing a thin issue defeats the door's own motivating scenario (Denis dictating by phone);
blocking on a question is the rigorizer D031 explicitly puts elsewhere (M440's `## As understood`
step, applying to every intake door alike, not specially to this one).

**Cost, accepted rather than hidden:** S1019 measured the same class of job at $1.86 loose against
$0.74 tight, frame quality being the entire difference. An item `create`d from a bare-title issue
runs loose until something — a future rigorizer, or a human editing the frame — tightens it.

**(2) The marker write-back is the idempotence mechanism, and it is structural, not a cache.**
`list_events()` re-derives "has this issue already produced an item" by reading the issue's body
for the marker on every call — the same no-persisted-mapping discipline `open()` already uses in
the other direction (`board/github.py`'s own docstring). `ingest()`'s `create` branch calls
`adapter.project(item, ref)` on the source issue synchronously, inside the same call that wrote the
new item, before returning — so the very next read of that issue's body already shows it as
ingested. The consumed-log's `event_id` dedup remains a second, independent backstop, unchanged
from the other three verbs.

**Rejected: a cache or mapping file recording "issue N already ingested."** Would duplicate
information the marker already carries, and would need its own consistency argument against the
git log — precisely the shape `board/github.py`'s docstring already rejects for `open()`.

## What this does not close

A true concurrent-`ingest()` race — two calls reading the same markerless issue before either
writes the marker back — is not solved here. Named in design.md ("what this does not attempt")
rather than silently assumed away: nothing in this repository calls `ingest()` concurrently today,
and the fleet's own concurrency rule (`orchestration.md`, "changes touch or might touch the same ->
SERIALIZE") already requires this class of hazard to be handled by not running two writers against
one tree at once, not by a lock this change would have to invent and test alone.
