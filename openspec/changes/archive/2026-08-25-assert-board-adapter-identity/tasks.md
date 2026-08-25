## 1. Baseline

- [x] 1.1 `make check` at HEAD, verbatim result captured.
- [x] 1.2 `make test-boardlive` at HEAD (identity: `iorlas`, already active), verbatim result
      captured.
- [x] 1.3 Determine, from GitHub's documented per-repo issue-access model, whether the
      partial-visibility failure S242 inferred is reachable for `GET
      repos/{owner}/{repo}/issues` — record the finding in `design.md` regardless of the answer.

## 2. Implement

- [x] 2.1 `GitHubIssuesAdapter.__init__`: add `self.identity: str | None = None`.
- [x] 2.2 `_ensure_identity()`: resolve `gh api user`'s `.login` once, memoized, best-effort (never
      raises; leaves `identity` as `None` on failure).
- [x] 2.3 `_issues()`: call `_ensure_identity()` at the top, before the issues call.
- [x] 2.4 `_api()`: include `self.identity` in the `BoardError` message when set.
- [x] 2.5 Confirm no change to `BoardAdapter`, `inbox.py`, or `runtime/loop.py` — identity stays
      inside the concrete adapter (design.md, rejected-alternative section).

## 3. Test

- [x] 3.1 `FakeGh` (`tests/board/test_github_create.py`) gains a `user` response; existing three
      tests still pass unmodified in assertion, proving the change is invisible to callers that
      never touch `.identity`.
- [x] 3.2 New unit test: after a `list_events()` call through the fake transport,
      `adapter.identity` is the fake login.
- [x] 3.3 New unit test: a failing `_api` call's `BoardError` message names the resolved identity.
- [x] 3.4 New unit test: `_ensure_identity()` itself failing (fake `user` call errors) leaves
      `identity` as `None` and does not stop the triggering read from raising its own, correct
      error.
- [x] 3.5 `tests/board/test_reprojection.py` (`boardlive`): after a real read, assert
      `adapter.identity == BOARD_REPO.split("/")[0]` — no new account name introduced, read from
      the existing constant.

## 4. Spec

- [x] 4.1 `board-projection/inbox` spec delta: ADDED requirement — the GitHub adapter resolves and
      records its authenticated identity on every read, without ever handling a credential.

## 5. Verify

- [x] 5.1 `make check` green, verbatim result captured.
- [x] 5.2 `make test-boardlive` green against real `BOARD_REPO`, verbatim result captured,
      identity active at run time noted; restore whatever identity was active before this session
      afterward.
- [x] 5.3 `openspec validate assert-board-adapter-identity --strict` passes.
- [x] 5.4 Archive, then re-run `make check`.
