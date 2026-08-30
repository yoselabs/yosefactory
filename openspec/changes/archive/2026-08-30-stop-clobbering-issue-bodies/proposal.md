## Why

`GitHubIssuesAdapter.project()` (`src/yosefactory/board/github.py`) PATCHed both `title` and
`body` unconditionally on every call, and `body` was always a freshly rendered stub (marker +
state line + goal). Measured live on `yoselabs/yosefactory` today: two issues carrying long,
hand-written specifications were reduced to the marker line, a state line, and the goal sentence
by an ordinary projection run. GitHub keeps no body history a script can recover — both were
restored by hand from a transcript; without that transcript the text was gone.

This is now on a path that runs on every run: the `project` job in `yoselabs/factory-state` calls
`project_all()` unconditionally (so a finished item's issue gets closed), which calls
`project_one()`, which calls `adapter.project()` unconditionally for every open item, every run.

No K project 160 promotion names this — there is none. This is a director-dispatched fix from a
live data-loss incident, not a promotion from the design record.

## What Changes

- `src/yosefactory/board/github.py`: `project()` no longer sends a body PATCH unconditionally.
  It reads the issue's current body first; if the item marker (`_extract_item_id`) is already
  present, only `title` is PATCHed and the body is left untouched, byte for byte. If the marker
  is absent — the one legitimate case, `ingest()`'s create path projecting a freshly-adopted,
  markerless, possibly human-authored issue — the marker line is prepended to whatever the body
  already held, and everything else survives.
- `src/yosefactory/board/github.py`: `_render()`'s body half drops the `State: <state>` line.
  Only `open()`'s create path still calls it for a body (a fresh issue has no human text yet, so
  the rendered stub is legitimately all there is); state is already carried by the title
  (`[state] goal`), so the body's own copy would go stale the moment `project()` stops touching
  an already-marked issue's body — which is now always.
- `openspec/specs/board-projection/inbox/spec.md`: one new (ADDED) requirement, "Projection
  never removes text it did not write" — the property this change establishes, as a spec
  scenario rather than only a code comment.
- Tests: `tests/board/fake_gh.py` (the shared in-memory `gh api` fake, pulled out of
  `test_github_create.py`, extended with a bare single-issue GET — `project()`'s new preflight
  read); `tests/board/test_github_project_preserves_body.py` (new) proving a human-authored body
  survives projection, title still moves on a state change, a markerless issue gets the marker
  prepended rather than replaced, and an already-marked issue's second projection sends no body
  PATCH at all.

## Capabilities

### Modified Capabilities

None modified — `board-projection/inbox`'s existing requirements ("GitHub Issues implements the
adapter without becoming the interface", the interface's five-method shape, etc.) are untouched;
their text is not renamed or reworded by this change.

### Added Capabilities

- `board-projection/inbox`: one new requirement, "Projection never removes text it did not
  write", covering `project()`'s body-preservation behaviour.

## Non-goals

- Not changing `project_one`'s find-or-create call to `adapter.open()` for an item with no issue
  — flagged in the dispatch as a deliberate widening (a planner-invented item now opens issues
  under the `project` job that runs every run), not a defect, and out of scope here. See
  `design.md`'s note on the interaction: this fix does not make that behaviour worse or better,
  it only stops the *body* half of the very next `project()` call in the same pass from
  destroying whatever `open()`'s own creation (or a human's pre-existing issue, on the
  markerless-adoption path) wrote.
- Not adding a body-content diff, a "last synced" marker, or any mechanism to *merge* future
  factory-authored fields into a human-edited body. The chosen shape avoids the conflict
  entirely by never touching an already-marked body again — see `design.md` for the two shapes
  considered and rejected.
- Not touching `close()` or `comment()` — neither ever overwrote the body; `close()` already
  reads-before-acting the same way this change teaches `project()` to.
- Not running `make test-boardlive` against a live repo as part of this change's own
  verification — see `design.md`'s "What this does not prove".

## Impact

- `src/yosefactory/board/github.py`
- `openspec/specs/board-projection/inbox/spec.md`
- `tests/board/fake_gh.py` (new)
- `tests/board/test_github_create.py` (trimmed to import the shared fake)
- `tests/board/test_github_project_preserves_body.py` (new)
