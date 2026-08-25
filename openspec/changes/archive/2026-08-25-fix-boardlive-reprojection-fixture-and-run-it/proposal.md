## Why

S243 (K project 160, cluster C6): `tests/board/test_reprojection.py` is the only automated check
that the board code works against real GitHub rather than a fake, and one of its two tests has
been red since before today's work — invisibly, because `pyproject.toml`'s `addopts` correctly
excludes the `boardlive` marker from `make check`. The exclusion is right (the marker mutates a
real repo and needs `gh` auth); nothing running the marker on any schedule, workflow, or release
point is the defect. D031 (open-issue-becomes-backlog-item) just made the board the factory's
intake, which makes this the only live check under the intake path, and it was red.

## What Changes

- **Fix the fixture, not the product.** `test_reprojection.py`'s `repo` fixture is
  `tmp_path / "repo"` — a bare directory, never `git init`-ed. `ingest()` correctly calls
  `runtime.turn.commit()`, which correctly refuses to run `git add` outside a git repository.
  `test_inbox.py`'s `repo` fixture already does this right (`git init` + identity + a seed
  commit); `test_reprojection.py`'s does not. Verified directly: running the marker at HEAD
  reproduces the exact `TurnError: git add failed: fatal: not a git repository` from S243, and the
  fixture omission is the only difference between the two files' otherwise-identical `repo`
  fixtures.
  - This is **not** a product defect. `ingest()`'s commit behavior is exactly what
    `board-projection/inbox`'s "A command's effect is committed to git, not left in the working
    tree" requirement demands. S243's own "looks like a fixture problem" reading was correct;
    this change is the diagnosis it deferred.
- **Make the marker runnable.** Add `make test-boardlive`, mirroring the existing `make test-live`
  target exactly (same shape: excluded from `check`, run deliberately, documented inline in the
  Makefile as to why). Document it as a required step before merging or releasing any change that
  touches `src/yosefactory/board/` — the one place in the repo where "the tests are green" and
  "the board actually works against GitHub" are different claims.
- New `board-projection/inbox` requirement naming that the live receipt is runnable on demand and
  why it stays outside `make check`.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `board-projection/inbox`: ADDED requirement — the `boardlive`-marked tests SHALL be runnable via
  a dedicated `make` target outside `make check`, and a change touching board code SHALL run it
  before merge.

## Impact

- `tests/board/test_reprojection.py` — `repo` fixture now `git init`s (and configures identity,
  seeds a commit) exactly like `test_inbox.py`'s.
- `Makefile` — one new target, `test-boardlive`.
- `CLAUDE.md` — a line under Stack/Reuse pointing at the new target as the release-verification
  step for board changes.
- No change to `src/yosefactory/board/` or `src/yosefactory/runtime/turn.py` — the product code
  under test is correct.

## Non-goals

- Not weakening `pyproject.toml`'s `addopts` exclusion — `boardlive` stays out of `make check`.
- Not a CI workflow / scheduled runner. This is a single-operator repo (D111: no daemon,
  orchestrator, or queue); a scheduled GitHub Actions job would need a stored `gh` credential
  scoped correctly (S242: this machine has two `gh` identities and `BOARD_REPO` is visible to only
  one — a wrong-identity 404 in CI would be silent unless the workflow itself asserted the
  identity), which is disproportionate infrastructure for a check with exactly one operator to run
  it. A deliberate `make` target, discoverable the same way `test-live` already is, matches the
  repo's existing pattern and costs nothing to maintain. Revisit if this check is still not being
  run some weeks from now (that would be evidence a manual step isn't enough).
- Not fixing S242 (the two-`gh`-identity confusion) itself.
- Not adding coverage beyond what `test_reprojection.py` already asserts.
