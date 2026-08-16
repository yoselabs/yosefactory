## Why

Dispatching the a2web run (D014's kill-criterion unit, window closes 2026-08-19) surfaced that
`take_turn` calls `publish(places, record)` unconditionally at every terminal site, and `publish`'s
only "off switch" is the absence of an `origin` remote. With `~/Workspaces/a2web` a real, remote-
configured repository, the caller had no way to run a turn against it locally-only short of mutating
the repository's git remote for the duration of the run — which the harness's own permission
classifier correctly refused as a repo-configuration change. **The blocker is the finding**: D022
granted push; nothing in it made publication mandatory, and a caller with no way to decline something
merely granted does not have a grant, it has a requirement.

## What Changes

- **`Places` gains `publish_queue: bool = True` and `publish_workspace: bool = True`.** The control
  lives on `Places`, not on `take_turn` — see Decision 1.
- **`publish()` checks each flag before calling `push_repo` for that place.** A declined place never
  reaches `push_repo`, never touches git, and is reported as `status="declined"`, a fourth value
  alongside `"pushed" | "skipped" | "rejected"` — see Decision 3.
- **No change to `take_turn`'s signature or to any existing call site's behaviour.** `Places.local`
  and every existing constructor call that supplies no opinion keeps publishing both places, exactly
  as today — see Decision 2.
- **`openspec/specs/turn-publication/spec.md` gains one new requirement** (pure addition, no existing
  header or scenario title touched): declining is a first-class, distinct outcome from having nothing
  to publish to.

## Decision 1 — where the control lives: `Places`, not `take_turn`

A `publish: bool` parameter on `take_turn` was the first shape considered and is the wrong one for
two reasons, both structural rather than stylistic:

- **`Places` already is where a turn declares which repositories it touches** (`Places`'s own
  docstring: "The four roles one `repo: Path` used to play at once, named separately"). Whether a
  role may be published is a property of that role, the same way `queue_lock`/`workspace_lock` are —
  not a separate axis bolted onto the function that consumes `Places`.
- **A single `publish: bool` cannot express the case this dispatch actually needed**: publish the
  queue (the platform's own bookkeeping, which the operator owns outright) while declining the
  workspace (a foreign repository on first contact, where looking before publishing is exactly the
  posture wanted). A queue you own and a workspace you are a guest in are different cases, and D014's
  own architecture already treats them as different `Places` fields for every other purpose (separate
  locks, separate identities under `turn-places`). One boolean would force them to share an answer;
  two fields let a caller give each its own.

`take_turn`'s signature is therefore unchanged. The caller decides per place, at the point it already
decides everything else about where a turn's repositories live.

## Decision 2 — the default stays publish

D022 grants push; this change does not revisit that grant, only whether it can be declined. Flipping
the default to "do not publish" would be a second, unrelated change — every existing caller of
`Places.local` or a bare `Places(...)` construction publishes both repositories today, and three
`test_turn_cycle.py` tests assert exactly that (`test_an_advanced_turn_publishes_workspace_before_queue`
and friends). Changing the default would silently stop publishing for every one of them, trading a
missing-decline bug for a missing-publish one — a worse trade, since D014's own measurement depends on
commits actually reaching a2web once the operator has looked and approved.

**Chosen: `True` for both fields.** A caller that wants to look before publishing states that intent
explicitly (`publish_workspace=False`), exactly as this dispatch now can. Nothing about existing
behaviour changes for a caller that states no opinion.

## Decision 3 — declined is not skipped, and is checked structurally, not by comparing strings

`push_repo` already returns `"skipped"` for a place with no `origin` — a fact about the repository.
`"declined"` is a fact about the caller's instruction. Conflating them would be the same discriminator
error already recorded four times in this codebase (`budget_exhausted` folded into `task_error`,
`needs_approval` folded into `blocked`, a harness kill recorded as `enforced_by: agent`, and the
`FAILED`-for-vocabulary-vs-`FAILED`-for-verification pair `teach-event-vocabulary` had to tell apart
by hand). A fifth would be the same mistake with more evidence against it.

The distinction is structural, not incidental: `publish()` checks the flag **before** calling
`push_repo` at all. A declined place's `push_repo` is never invoked, so `"declined"` can never share a
code path with `"skipped"` — there is no shared branch where the two could be conflated by a future
edit, only two separate returns.

## Noted, not fixed — publication has no durable trace

`publish()` runs strictly after the turn record is committed (`turn-publication`'s own second
requirement), so there is no legal moment inside a turn's append-only log to write a publication
result into it — the record is already a true, closed statement about what the turn did by the time
`publish` produces anything to say. This is a named open item from the change that built publication,
not new here. `declined` inherits the same gap: it is visible to whatever caller holds `publish()`'s
return value and invisible to anyone reading the ledger or the item's trail afterward. **Out of scope
for this change** — giving publication a durable trace is a different change, with its own argument
about where that trace would legally live.

## Non-goals

- **Not a change to `verify.may_write_done`, any `IsolationPolicy` posture, or the vocabulary
  pointer.** Publication is downstream of the gate, not part of it.
- **Not a retry or force-push mechanism.** `turn-publication`'s existing "never forces, tags, deletes,
  or creates a remote" requirement is untouched.
- **Not a change to which repository publishes first.** Workspace-before-queue ordering is preserved;
  declining one does not reorder the other.

## Impact

- `src/yosefactory/runtime/turn.py` — `Places` gains two fields; `publish()` checks them.
- `openspec/specs/turn-publication/spec.md` — one new requirement, addition only.
- No test currently asserting publish behaviour needs to change (default preserved); new tests added
  for the decline path.
