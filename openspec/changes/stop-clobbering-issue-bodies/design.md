## Context

`GitHubIssuesAdapter.project()` renders a fresh `(title, body)` from the item's current fold on
every call and PATCHes both, unconditionally, every time `project_all()` runs — which is every
turn-loop wake and, per the dispatch, every `project` job run in `yoselabs/factory-state` (that
job calls `project_all()` unconditionally so a finished item's issue gets closed). `_render()`'s
body was `<marker>\nState: <state>\n\n<goal>\n` — a complete replacement of whatever the issue's
body held before. GitHub's Issues API keeps no body revision history a script can recover, so
each PATCH is destructive and irreversible the instant it lands.

Measured live on `yoselabs/yosefactory` today: two issues carrying long, carefully-written
specifications were reduced to the three-line stub. Both were restored by hand from a transcript
that happened to exist; the property "the specification was gone" was one missing transcript away
from being permanent.

## Constraints carried from the dispatch

- The body must keep carrying `<!-- yosefactory:item=<id> -->` — `_find_ref` (github.py:111)
  searches for it, and design.md D2 / the re-projection acid test (`board-projection/inbox`
  spec's "Ref resolution has no other source of truth") depend on it surviving.
- `open()`'s authoring path is legitimate and must not change: an item the planner invented has
  no human text, so the rendered body is genuinely all there is for a freshly created issue.
- State (`item.state`) is a real projection of the fold and must still reach the issue somewhere
  — but the title already carries it (`[state] goal`), so the question is whether the *body*
  needs a second copy.

## Options considered

**A. Diff-and-merge**: fetch the current body, parse out a "factory-owned region" (marker +
state line) by some delimiter, splice in the new region, keep everything else. Rejected: requires
inventing and maintaining a delimiter convention (start/end markers) that both `open()`'s writer
and `project()`'s reader must agree on forever, and any body a human wrote *without* using that
convention (every issue on the board today) still has nothing marking where the factory's region
ends and the human's begins — the marker is the only thing the code already promises is at a
known position (the `<!--...-->` line), and everything after it is currently unstructured prose.

**B. Stop touching body once the marker is present; write the marker once, on first sight, and
never again.** `project()` reads the current body, checks whether the marker is already there.
If yes: body is left alone entirely, no PATCH sent for it. If no (only `ingest()`'s create path
hits this — a freshly-adopted, possibly human-authored, markerless issue): prepend the marker,
send the result once. Chosen. It needs no new convention — `_extract_item_id` already exists and
already is the one position anyone can agree on — and it makes the "never removes text it did
not write" property literal: after the marker exists, `project()` makes zero body writes, ever,
to that issue, for the rest of its life.

**C. Move state (and everything else rendered) out of the body entirely, onto a GitHub-native
field (a label, a project-board column).** Rejected for this change: `board-projection/inbox`'s
own spec ("GitHub Issues implements the adapter without becoming the interface") already forbids
exposing GitHub-specific concepts (label, milestone) through the `BoardAdapter` Protocol; solving
this defect by reaching for one would reopen a decision this change has no mandate to reopen, and
title-only state was already suficient (title already carries `[state]`, unconditionally, and
`project()` still PATCHes title every call — nothing about state visibility regresses).

## Decision

**B.** `project()`:
1. Renders `title` fresh every call (unchanged; disposable, no history to lose).
2. Reads the issue's current body once (`gh api repos/{repo}/issues/{ref}`, the same shape
   `close()` already uses).
3. If `_extract_item_id(body)` is not `None` — the marker is present — PATCHes `title` only. No
   `-F body=@-` argument is sent at all; the issue's body is not part of this API call.
4. If the marker is absent, prepends `_marker_line(item.id)` (+ a blank line) to the existing body
   and PATCHes both `title` and the prepended body. This is the only body-write path left in
   `project()`, and it only ever *adds* the marker line — it never removes or reorders anything
   already in the body.

`_render()`'s body half (used only by `open()` now) drops the `State: <state>` line: state is
already carried by the title, and a second, body-side copy would go silently stale the moment
`project()` stops touching an already-marked body — which is now permanent for that issue's
lifetime after the first successful projection. Leaving a copy that can never update again is
worse than never having had one.

## The marker/state/human-text property, stated as an invariant

> Once an issue's body carries the item marker, `project()` never writes to that body again —
> not the marker (already there), not state (lives in the title only), not the goal (rendered
> once, by `open()`, at creation, and never refreshed). Everything a human adds below the marker
> after that point is permanent from this adapter's perspective.

This is stricter than the dispatch's literal ask ("never removes text it did not write") — it
additionally never *adds* text it did not write, once the marker exists. A weaker shape (keep
overwriting a "factory-owned header" section on every call) was considered and rejected under
Option A for the reason given there: no reliable boundary exists between a factory header and
human prose in an already-existing issue that predates this change.

## Interaction with `open()`'s find-or-create widening

The dispatch flags, as a known and deliberate widening (not to be changed here): `project_one`
calls `adapter.open()` unconditionally for every item, including one with no issue yet, so under
the `project` job (which now runs every run) a planner-invented item opens a fresh issue on the
workspace. This change does not touch that call or make it more or less frequent. It only changes
what the very next line, `adapter.project(item, ref)`, does to that issue's body once opened:
before this change, the freshly-`open()`ed issue's body (marker + goal, no human text yet) would
immediately be re-rendered and re-PATCHed by `project()` — a harmless no-op today since `open()`'s
own render and `project()`'s own render agreed, but only by coincidence of both calling the same
`_render()`. After this change, `project()` sees the marker `open()` just wrote, and sends no body
PATCH at all on that first call either — one fewer API call, and one fewer opportunity for the
two renders to someday disagree.

## What this does not prove

- **Not run against real GitHub.** `make test-boardlive` (`tests/board/test_reprojection.py`,
  marked `boardlive`) mutates a real throwaway repo (`BOARD_REPO`) and needs `gh` auth; it is
  excluded from this change's own verification per the dispatch's "do not push" / scope
  boundary, and per `orchestration.md`'s Docker-only execution constraint (that target isn't run
  from this session). The unit-level fake (`tests/board/fake_gh.py`) proves the same code path
  the same way `test_github_create.py` already did for the create path — it is a receipt that
  the *logic* is correct against a faithful model of the API's field-level PATCH semantics, not a
  receipt that GitHub's actual PATCH endpoint behaves as modeled. The two prior live acid-test
  runs (`test_reprojection_acid_test`, `test_rejected_command_is_a_visible_reply_on_the_thread`)
  are the standing evidence that `gh api ... -X PATCH` with only `title=` set leaves `body`
  untouched on the real API; this change relies on that already-established behaviour rather than
  re-deriving it.
- **Not a receipt that the two live issues already damaged are un-damageable going forward by
  some other code path.** Only `project()` is fixed. If another writer PATCHes an issue's body
  directly (none does today), this change does not guard against it.
- **A green `make check`/unit-test suite proves the wiring compiles and the logic is correct
  against the modeled API — not that the real `gh api` PATCH endpoint's field-omission semantics
  match the model exactly for every edge case (empty body, body containing the marker text as a
  quoted/escaped substring rather than a real HTML comment, etc.).** The pre-existing
  `test_reprojection_acid_test`'s repeated real-API runs are the reason to trust the omission
  semantics specifically; nothing new in this change re-verifies that against the live API.
