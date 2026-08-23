# ADR-0015 — `gate_rejected` is a new non-transitioning event; an answer's text is copied onto the item, not read cross-file

**Status:** Accepted
**Date:** 2026-08-23
**Supersedes:** —
**Superseded by:** —
**Revisit trigger:** `backlog.context()`'s folded value is measured larger than the frame it
accompanies on three items (D030's own trigger, restated here because it governs this ADR's shape
too) — at which point the event/answer choices below need revisiting alongside the channel itself.
Also revisit if a second consumer ever needs the answer text independent of the item (today only
the item's own executor reads it) — that would be an argument for reference-not-copy this ADR
rejected.

## Context

[[D030]] rules that a turn's inherited context is folded from the item's own event log and stays
separate from the frame. Filling that in required two choices the decision left to the build:
what event carries a gate rejection onto the item, and how an answer's text — which today lives
only in the question log ([[S1038]]) — reaches the item at all.

## Decision

**1. A new event, `gate_rejected`, legal from `doing`, changing no state.**

Checked against the existing table first: every event reachable from `doing` either transitions
state (`blocked`, `falsified`, `failed`, `needs_split`, `done`) or is one of the two D030 excludes
for this purpose (`frame_amended`, `note`). Reusing `failed` was rejected — a gate rejection is not
an agent-reported failure, and routing it through `failed` would burn the attempt counter
(`_poison_if_exhausted` reads `failed`) for a rejection that must remain retryable within the same
attempt, the same way it implicitly was before this change (no event at all was written).

**2. The answer's text is copied onto the item at `unblocked` time, not read from the question log
when `backlog.context()` folds.**

D030's own wording decided this: the context channel is "folded from the item's own event log."
A fold that reached into the question file to resolve `resolution.qid` at read time would make
`backlog.context()` depend on two files, breaking that property and making it the only reader in
`protocol/backlog.py` that is not a pure function of one `FoldedLog`. `apply_answers()` already
reads the closing question record to decide whether to unblock at all; attaching `answer` to the
same `unblocked` append it already writes costs one field, not a new read. The question log keeps
the canonical `answered` record; the item's copy is read-only and is never the record a later
decision is made from — real duplication, accepted because it is written once and never
re-derived.

**Rejected alternative for (2):** resolve `answer` at fold time by loading the referenced question
file. Rejected for the reason above — it would work, but it contradicts D030's stated shape rather
than implementing it, and it would make `context()` behave differently from every other fold in
this module.

## Consequences

- `backlog.ITEM.rules` gains one entry; `openspec/specs/backlog-item-format/spec.md`'s live
  vocabulary table (read by `Invocation.vocabulary` at runtime, per ADR-0012/`unstick-the-backlog`'s
  own precedent) was updated directly, not deferred to archive.
- `unblocked.resolution` gains an optional `answer` key. Existing `unblocked` records without it
  fold correctly — `backlog.context()` treats its absence as "no answer to carry," not an error.
- `gate_rejected` never triggers `_poison_if_exhausted` and never changes `attempt`'s meaning: it is
  informational only, and an item may carry any number of them while remaining `doing`.
