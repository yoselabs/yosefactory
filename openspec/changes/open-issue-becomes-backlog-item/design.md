## The property `create` doesn't share with the other three

`set_priority`, `answer`, `cancel` all act on an item git already holds — the board is a mirror
throughout, `ingest()` never needs to invent anything. `create` starts from nothing: between the
issue being opened and `ingest()` running, the tracker holds the only copy of a real request. D031
accepts that window explicitly and requires it be kept short **by design, not by luck**. Two
failure modes follow, and both must be prevented structurally, not merely detected:

1. an issue ingested twice, producing two items for one request;
2. an issue edited between opening and ingest, landing with the pre-edit text.

## Why the marker write-back closes both, and why it is not a cache

`board/github.py`'s own docstring already states the precedent this change follows: `open()` has
no mapping file, and re-derives "does this item already have a thread" by searching the board for
the marker line on every call. The re-projection acid test (`test_reprojection.py`) exists
precisely to prove that property — delete every issue, re-run, get the same board back, with
nothing but git and the board consulted.

`create` is the same idea run in the other direction: instead of "does this item have a thread",
`list_events()` asks "does this issue have an item" by searching the same marker, and an issue
without one is exactly the intake candidate. The fix for double-ingest is therefore not a
consumed-log lookup (though the consumed-log's `event_id` dedup is still there as a second,
independent backstop — the same one the other three verbs already rely on) — it is closing the
window in which the answer to "does this issue have an item" can be stale:

```
  list_events()             ingest()                      list_events()
  sees issue #7,      ->    creates itm-xyz,        ->    sees issue #7,
  no marker                 calls adapter.project()        HAS marker -- not a candidate
  (candidate: create)       (marker written, same call)
```

`ingest()`'s `create` branch calls `adapter.project(item, ref)` on the **same issue `ref` the event
arrived on**, synchronously, inside the same call that created the item — not queued, not a
follow-up turn. By the time `ingest()` returns, the only window left is "two `ingest()` calls
running concurrently against the same unmarked issue," which is the same concurrency hazard
Article III / the concurrency rule already require the fleet to serialize around (`orchestration.md`
"changes touch or might touch the same file -> SERIALIZE") and which this repository runs as one
process at a time regardless. Not solved here because nothing in this repository's `ingest()`
call pattern currently needs it solved — named so it is not silently assumed safe under a future
concurrent-poller design.

**The edited-issue race closes for free, for a different reason: `list_events()` never caches.**
Title and body are read directly from the `gh api` response at the moment `ingest()` runs, the
same call that decides "this issue has no marker." There is no earlier read of the same issue to
go stale against. An edit *after* ingest lands (post-marker) is `frame_amended` territory — out of
scope for this change, same as it is for a hand-created item edited after the fact.

## The thin-issue choice, stated and costed

A GitHub issue is a title and a body. `backlog.ITEM`'s `created` rule requires `goal`, `method`,
`assumptions` (D019) — a GitHub issue supplies at most one of those cleanly. Three shapes were on
the table:

1. **Refuse a thin issue** (no body, or body under some length). Rejected: this is exactly the
   motivating scenario D031 names — *"Denis dictates by voice, away from the keyboard"* — and a
   phone-typed one-liner is precisely what a length gate would bounce. Refusing the door's own
   primary use case defeats the point of building the door.
2. **Block the item pending a question**, i.e. immediately raise a `blocked`/`kind: question` on
   the fresh item asking for goal/method/assumptions. Rejected: this *is* the rigorizer D031
   explicitly puts out of scope ("M440's `## As understood` step... applies to every door
   equally"). Building a bespoke one here for this door only would contradict that division and
   would need its own design (what question, what timeout, who answers).
3. **Accept it with a degenerate frame, built mechanically from what the issue actually has.**
   Chosen. `goal` = the issue title (verbatim); `method` = the issue body (verbatim), or a fixed
   placeholder string if the body is empty; `assumptions` = a fixed literal stating the frame was
   never rigorized. No judgment call, no LLM call, no blocking — just enough structure to satisfy
   `backlog.ITEM`'s required fields honestly rather than by padding them with invented content.

**The cost, named rather than hidden:** S1019 measured the same a2web job at $1.86 loose against
$0.74 tight, frame quality being the entire difference. A `create`d item from a one-line issue
will run loose until something rigorizes it. This change buys the door; it does not buy a good
frame through it, and does not pretend to — that is D031's own boundary, restated here as the
concrete cost of respecting it.

`loop` on the `created` event (required alongside `frame`) is set to the literal `"board-intake"`,
distinguishing an item that arrived through the tracker door from one a planning loop proposed
(`runtime/turn.py`'s existing `{"loop": loop, **event}` writers use the calling loop's own name;
`board-intake` is this door's name for the same field, not a new concept).

## Why `create` is not in `_APPLIERS`

The three existing appliers share a signature: `(repo, item_id, payload, *, actor) -> (detail,
touched_path)`, because all three already know which item they're acting on. `create` has no
`item_id` until it manufactures one, and it is the only command that needs to call back into the
adapter (`project()`) after acting — the other three only reach `adapter.comment()`, and only on
rejection, from `ingest()` itself. Folding `create` into the same table would need a different
signature for one row and a special call after every row "just in case," which hides the one case
that actually needs it. `ingest()` branches on `event.type == "create"` before the `_APPLIERS`
dispatch instead, and says why in a comment at the branch.

## What this does not attempt

- **No rigorizer**, per D031 and per the "what this does not decide" section above.
- **No concurrent-ingest lock.** Named above; out of scope because nothing calls `ingest()`
  concurrently today.
- **No comment-scanning on a markerless issue.** A comment posted on an issue before it has been
  ingested has no item to act on; `list_events()` skips comment collection for such an issue this
  pass and picks its comments up normally once it has a marker and is a normal command thread.
