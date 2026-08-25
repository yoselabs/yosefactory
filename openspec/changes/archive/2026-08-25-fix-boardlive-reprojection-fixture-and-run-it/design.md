## Context

S243 named two facts and left one undiagnosed: `test_reprojection.py::test_rejected_command_is_a_
visible_reply_on_the_thread` fails at HEAD and pre-existing (`a7ad392~1`), and `make check` never
runs it (`pyproject.toml:72`'s `addopts` excludes `not live and not boardlive`). It flagged the
failure as "looks like a fixture problem... but it was not diagnosed further." D031 makes this the
one live check under the board, which is now the factory's intake, so an unexamined red test here
carries more weight than it did a day ago.

## Diagnosis (verified, not assumed)

Ran `PREK_ALLOW_NO_CONFIG=1 uv run pytest -q -m boardlive tests/board/ -k test_rejected_command...`
at HEAD (`c59d209`). Reproduced exactly:

```
src/yosefactory/runtime/turn.py:518: TurnError
E  TurnError: git add failed: fatal: not a git repository (or any of the parent directories): .git
```

Traced the call: `ingest()` (`inbox.py:201`) calls `turn_commit(repo, [path], ...)` on a rejected
command, which calls `runtime.turn.commit()`, which runs `git add -- <paths>` inside `repo`.
`test_reprojection.py`'s `repo` fixture is:

```python
@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return tmp_path / "repo"
```

— a path, never created, never a git repository. Compare `test_inbox.py`'s `repo` fixture (same
module family, same `ingest()` under test), which does `root.mkdir()`, `git init -q`, sets
`user.email`/`user.name`, and seeds one commit — specifically because, per that file's own
comment, "`ingest()` now commits what it applies... so a bare directory no longer exercises the
code path these tests are for." `test_reprojection.py` was never updated to match when `ingest()`
grew its commit behavior. That is the whole defect: a fixture that fell out of sync with the code
path it drives, in a file excluded from the suite that would have caught the drift on the next
green run.

**This is not a product defect.** `commit()` refusing to `git add` outside a git repository is
correct — it is the same refusal any git operation would give, and a real board's queue repository
is always a real git checkout. `ingest()` calling `turn_commit()` on every applied-or-rejected
event, including rejections (so the consumed-log entry lands), is exactly what
`board-projection/inbox`'s existing "A command's effect is committed to git, not left in the
working tree" requirement demands, verbatim, including the rejected-command scenario. S243's
"looks like a fixture problem" reading is confirmed correct; nothing in `src/yosefactory/board/`
or `src/yosefactory/runtime/turn.py` changes.

The other test in the file, `test_reprojection_acid_test`, passes today because it never triggers
a git commit inside `repo` on the failure path it exercises — `project_all()` only reads from
`repo`'s item logs and writes to the GitHub adapter; it never calls `turn.commit()` against
`repo`. Only the rejected-command path (`ingest()` → `turn_commit()`) touches `repo` as a git
target, which is why exactly one of the two tests was ever going to surface this.

## Decision: fix the fixture to match `test_inbox.py`'s, not add a workaround

`test_reprojection.py`'s `repo` fixture becomes: create the directory, `git init -q`, set a local
throwaway identity, seed one commit — byte-for-byte the same shape `test_inbox.py` already uses.
Rejected alternative: mock or bypass `turn_commit()` inside the acid test's own scope. Rejected
because the acid test's whole point (its own docstring: "run for real... never from this module's
own return values") is to prove the real path works; special-casing the commit call would remove
exactly the property under test.

## Decision: `make test-boardlive`, not a scheduled workflow

Three candidates were on the table (per dispatch): a manual `make` target, a scheduled/release
GitHub Actions workflow, or a documented step in a release checklist. Chose the `make` target,
documented as a required pre-merge step for board changes — reasons:

- **Precedent already exists.** `make test-live` is the identical shape: real cost/external state,
  excluded from `check`'s `addopts`, run deliberately. `test-boardlive` is the same pattern for a
  different resource (network + `gh` auth instead of model spend). Reusing a pattern the repo
  already trusts is cheaper than inventing a second one.
- **A scheduled CI runner needs a credential this machine's own `gh` setup makes non-trivial.**
  S242 (not fixed by this change): this machine holds two `gh` identities (`iorlas`,
  `emsteeldtomilin`); `BOARD_REPO` (`iorlas/yosefactory-board-receipt`) is visible only to the
  first, and the wrong one 404s loudly. A CI workflow would need its own stored token scoped to
  `iorlas` specifically — a secret to create, rotate, and audit for a single-operator repo, for a
  check that has exactly one person able to act on a failure. That is real, ongoing infrastructure
  weight this project's own constraints (D111: no daemon/orchestrator/queue; single-operator,
  `CLAUDE.md`) argue against absent evidence a manual step is being skipped.
- **This bears directly on whether "runs on a schedule" is even sound here.** If the identity
  problem is not resolved, a scheduled runner either needs its own credential (the point above) or
  inherits ambient `gh` state that could silently point at the wrong account — the exact failure
  mode S242 describes, just moved from a human's terminal to an unattended job where a wrong-repo
  404 is easier to miss. A deliberate, human-run command surfaces a wrong-identity failure to the
  person who can fix it on the spot; a cron job would surface it into a log nobody is looking at,
  which is the same invisibility S243 is about, one layer further out.
- **Revisit trigger:** if this check goes unrun across a real release of a board-touching change
  (the thing the manual step is supposed to prevent), that is evidence a human step isn't enough
  and a scheduled workflow should be built — at which point S242 needs fixing first, or the
  scheduled runner inherits its exact failure mode.

## Risks / what this does not prove

- **Verified once, this session, against the real `BOARD_REPO`** (see report). It does not prove
  the fixture fix is durable against a future change to `ingest()`'s commit behavior — only that it
  matches today's behavior, the same way `test_inbox.py`'s fixture does.
- **Does not prove a human will actually run `make test-boardlive` before every board-touching
  merge.** The target and the documentation make it easy and discoverable; nothing enforces it
  mechanically. That gap is named, not closed, per the Non-goals above.
- **Does not touch S242.** If a future scheduled-runner design is attempted, S242 is a
  precondition, not a detail — noted per the dispatch's explicit ask.
