## Why

[[D031]] (`~/Documents/Knowledge/Projects/160-ai-factory/decisions/D031-*.md`): every item this
factory has ever executed was written by hand — the machine can do work and cannot get work. D031
adds `create` as a fourth board intent command, alongside `set_priority` / `answer` / `cancel`, so
that an issue Denis opens on the tracker becomes a backlog item. Governing context: [[D028]] (the
tracker is authoritative for intent, never outcome — a new item is intent) and [[D029]] (the
tracker is an adapter layer; GitHub is the first).

`board/github.py::list_events()` today skips any issue with no `yosefactory:item=<id>` marker —
exactly the issue this change must stop skipping, since an issue about to be ingested has no item
yet by definition.

## What Changes

- **`create` joins the event vocabulary** (`board/event.py`'s `TYPES`). Unlike the other three, it
  is never parsed from a comment's `/word` syntax — the act of opening an unmarked issue *is* the
  command. `parse_command()` is unchanged.
- **`GitHubIssuesAdapter.list_events()` emits a `create` event for every issue with no item
  marker**, instead of skipping it — title and body carried verbatim in the payload, read fresh at
  list time (design.md, "why the edited-issue race closes for free").
- **`board/inbox.py::ingest()` grows a `create` branch**, structurally separate from the existing
  `_APPLIERS` table because `create` has no existing `item_id` to dispatch on. It builds a
  degenerate frame from the issue's title/body (design.md, "the thin-issue choice"), appends
  `backlog.ITEM`'s existing `created` event through `runtime.turn.append()` — no new item-log
  vocabulary — and then calls `adapter.project(item, ref)` on the *same* issue to imprint the new
  item's marker back onto it.
- **The marker write-back is the idempotence mechanism**, not a cache: `list_events()` re-derives
  "has this issue been ingested" by reading the issue's own body on every call, exactly as `open()`
  already does for the other three verbs (module docstring, "no mapping file"). Once `project()`
  lands, the issue is no longer markerless and `list_events()` stops offering it as a `create`
  candidate — see design.md for why this is the same closed-loop rather than a race.

## What does NOT change

- **No rigorizer.** D031 explicitly defers "is this frame any good" to M440's `## As understood`
  step, applying identically to every intake door. This change accepts a thin issue with a
  degenerate `method`/`assumptions` rather than blocking or refusing it — the cost is named in
  design.md, not hidden.
- **`set_priority` / `answer` / `cancel` and their `_APPLIERS` dispatch.** Untouched.
- **The `BoardAdapter` Protocol.** Still exactly five methods (`list_events`, `open`, `project`,
  `comment`, `close`); `create` is built entirely from the existing `project()`, no sixth method.
- **`board/projection.py`.** `project_all()` still only reads git and writes the board; this change
  does not touch it.

## Impact

- Affected specs: `board-projection/inbox` (vocabulary table gains a row; new requirement for the
  markerless-issue path and its idempotence).
- Affected code: `src/yosefactory/board/event.py`, `src/yosefactory/board/github.py`,
  `src/yosefactory/board/inbox.py`.
- New ADR: `decisions/0016-*.md` (the thin-issue frame choice and the marker-as-idempotence
  mechanism — both non-obvious build-time calls per `openspec/config.yaml`'s archive guidance).
