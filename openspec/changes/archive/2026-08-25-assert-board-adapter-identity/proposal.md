## Why

S242 (K project 160, cluster C6): `GitHubIssuesAdapter` names `self.repo` on every call —
deliberately, per the existing `board-projection/inbox` requirement that no call omits `--repo` —
but it never asserts **who it is**. Identity is ambient: whichever `gh` account is active answers
every call, and this machine has two. One account 404s against `BOARD_REPO` (loud, already
handled — `_issues()` raises `BoardError`); the other reads it fine. The 404 is not the risk.
**An account with partial visibility would return a shorter issue list and no error at all**, and
`ingest()` cannot tell "no commands" from "no permission." D031 made that list the factory's
intake, so a silently-truncated read is now a silently-dropped operator request.

## What Changes

- `GitHubIssuesAdapter` resolves and caches the authenticated `gh` login (`gh api user`'s
  `.login`) the first time it reads the board, exposed as `self.identity`. Every `BoardError` this
  adapter raises names that identity alongside the repo, so a failed or short read is diagnosable
  after the fact without a second manual `gh auth status` call.
- Resolution is best-effort and never blocks the read that triggered it: if `gh api user` itself
  fails, `identity` stays `None` and the triggering call proceeds or fails on its own terms.
- No credential is read, printed, logged, or stored — `gh api user` returns profile data (login,
  name, id), not the token that authorized the call. The class's existing docstring commitment is
  unchanged.
- New `board-projection/inbox` requirement naming this behavior, plus unit coverage against a fake
  `gh` transport (no network) and a live-receipt assertion (`test-boardlive`) that the resolved
  identity matches `BOARD_REPO`'s own owner.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `board-projection/inbox`: ADDED requirement — the GitHub adapter SHALL resolve and record which
  authenticated identity it is reading/writing as, on every board read, without ever handling a
  credential.

## Impact

- `src/yosefactory/board/github.py` — `GitHubIssuesAdapter` gains `self.identity` (resolved lazily
  in `_issues()`, the one choke point every read goes through) and enriches `BoardError` messages
  with it.
- `tests/board/test_github_create.py`'s `FakeGh` gains a `user` response so existing fake-`gh`
  tests keep passing unmodified in behavior.
- `tests/board/test_reprojection.py` gains a `boardlive` assertion that `adapter.identity` matches
  `BOARD_REPO`'s owner segment (no new account name introduced — read from the existing constant).
- No change to `BoardAdapter` (the five-method Protocol) or to any caller (`inbox.py`,
  `runtime/loop.py`) — identity lives entirely inside the concrete adapter, so nothing calls a
  sixth method on the interface `project_all()`/`ingest()` hold.

## Non-goals

- Not fixing the two-`gh`-identity situation on this machine, and not adding an
  expected-identity/mismatch-refusal config — that would need a value to compare against in CI,
  where the only credential is `GH_TOKEN` and there is no second identity to distinguish from a
  first. Recording who answered is the mechanism; refusing on mismatch is not, because there is
  nothing to mismatch against in the one place this must also work.
- Not adding a scheduled/CI board poller. `orchestration.md`'s D025 and the archived
  `fix-boardlive-reprojection-fixture-and-run-it` change already rejected that for S242's own
  reason (a scheduled runner would need its own credential scoped to one identity).
- Not building a detector for a silently-truncated read. This change makes such a read
  diagnosable after the fact (identity is on record); it does not add automated comparison against
  an expected count, which would need a source of truth for "how many issues should exist" that
  does not currently exist anywhere in this repository.
- Not touching `pyproject.toml`'s `boardlive` exclusion from `make check` (unrelated, and settled
  by S243's own change).
