## 1. Fix

- [x] 1.1 `src/yosefactory/board/github.py::project()`: read the issue's current body first
      (`gh api repos/{repo}/issues/{ref}`, same shape `close()` already uses); PATCH `title`
      only when the item marker is already present in the body.
- [x] 1.2 Same method: when the marker is absent, prepend `_marker_line(item.id)` to the
      existing body and PATCH both `title` and the prepended body — the one remaining body-write
      path, and it only ever adds the marker.
- [x] 1.3 `_render()`: drop the `State: <state>` line from the rendered body (state is carried by
      the title alone; a body-side copy would go stale the moment `project()` stops touching an
      already-marked issue's body).

## 2. Spec delta

- [x] 2.1 `openspec/specs/board-projection/inbox/spec.md`: one new ADDED requirement,
      "Projection never removes text it did not write", with four scenarios (human text
      survives, state moves via title only, marker prepended not replacing, `open()` unaffected).

## 3. Tests

- [x] 3.1 Pull the existing `FakeGh` fake out of `tests/board/test_github_create.py` into
      `tests/board/fake_gh.py`, extend it to model a bare single-issue GET (`project()`'s new
      preflight read) — `test_github_create.py` re-imports it, no behavioural change to that
      module's existing three tests.
- [x] 3.2 New `tests/board/test_github_project_preserves_body.py`:
      - a human-authored body below the marker survives `project()` unchanged
      - the title still moves on a state change while the body does not
      - a markerless issue gets the marker prepended, not replaced
      - a second projection of an already-marked issue sends no body PATCH at all (asserts the
        `-F`/`body=` arguments are absent from the second call)
- [x] 3.3 Confirm fails-before: with only `src/yosefactory/board/github.py` reverted to its
      pre-fix state (test files present), the new test module fails — proving the regression is
      real and the new tests catch it, not merely wired to pass. Evidence in the closing report.

## 4. Verify

- [x] 4.1 `make check` (Docker) green.
- [x] 4.2 `openspec validate stop-clobbering-issue-bodies --strict` passes.
- [x] 4.3 `make test-boardlive` NOT run against a live repo as part of this change (see
      `design.md`'s "What this does not prove") — the fake-based unit tests are this change's own
      receipt; the pre-existing live acid test already establishes that `gh api ... -X PATCH`
      with only `title=` set leaves `body` untouched on the real API.
