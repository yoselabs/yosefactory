## 1. `Places`

- [x] 1.1 Add `Places` (queue, ledger, queue_lock, workspace, workspace_lock) and `Places.local(repo)`
      to `runtime/turn.py`, reproducing `ITEMS`/`QUESTIONS`/`RUNS`/`LOCK`'s current derivation exactly.
- [x] 1.2 Add `_workspace_lock(places)`, the path-equality dodge that skips a second `flock` acquisition
      when `workspace_lock == queue_lock` rather than relying on unverified `fcntl` reentrancy.

## 2. Thread `Places` through `take_turn`

- [x] 2.1 `take_turn` takes `places: Places` instead of `repo: Path`.
- [x] 2.2 Queue lock wraps declare/apply-answers/pick/claim; workspace lock (via `_workspace_lock`)
      wraps the executor invocation and disposal.
- [x] 2.3 `items`, `apply_answers`, the marker-declare commit, and the claim commit all read/write
      `places.queue`.
- [x] 2.4 The executor call passes `places.workspace` as its `workspace` argument and `places.ledger`
      as `runs_dir`.

## 3. Thread `Places` through `_dispose` and `_finish`

- [x] 3.1 `_dispose` takes `places` instead of `repo`; the raised-question path writes to
      `places.queue`; `verify.may_write_done` is called against `places.workspace`.
- [x] 3.2 `_finish` takes `places`; `tree_is_dirty` targets `places.workspace`; the final commit
      (item, question, ledger record, ledger marker) targets `places.queue`.

## 4. Tests

- [x] 4.1 Update the shared `take()` test helper to build `Places.local(repo)`; no individual test body
      needed to change.
- [x] 4.2 Add a `workspace` fixture — a second, independent git repository with no queue directories.
- [x] 4.3 Add `take_split(queue, workspace, ...)` and cover: a foreign workspace gets no queue
      bookkeeping; the executor's `workspace` argument is the configured workspace, not the queue; a
      busy workspace lock blocks a turn before the agent runs even though the queue lock let picking
      happen; two different queues targeting one workspace still serialize (the keying is by
      workspace identity, not by dispatching queue).
- [x] 4.4 `make check` — 265 passed (260 existing + 5 new), lint and `ty check src` clean.

## 5. What this does not prove

- [ ] 5.1 **State, do not build, the receipt that would distinguish threaded from working.** [[S195]]:
      no test in this repository drives `take_turn` against a real executor: every test — including
      every new one in this change — calls a `FakeExecutor` that never runs a process or touches a
      real foreign repository. What §4's tests prove is that `Places`'s fields reach the right calls
      in the right order (`workspace` reaches the executor argument, `queue` reaches every bookkeeping
      write, the two locks key independently). None of it proves a real `claude -p` agent can act
      inside a real second repository end to end — authenticate, edit, commit, and have that commit be
      the one `verify.may_write_done` and the turn record both see.

      **The receipt that would close the gap**: an integration test, gated exactly like
      `tests/executor/test_integration.py` (skipped absent a pinned `claude` on `PATH`), that seeds a
      real second git repository as `workspace`, runs `take_turn` with `Places(queue=<tmp>,
      workspace=<that repo>, ...)` against the real `claude.run` executor with a trivial goal ("create
      a file and commit it"), and asserts: the commit lands in the workspace repository and nowhere
      in the queue; the queue repository grows no `backlog/`, `questions/`, or `ledger/` directories
      of its own bookkeeping leaking into the workspace; and the turn record in the queue's ledger
      names an outcome consistent with what actually happened in the workspace. This is not built
      here, per the director's instruction — it is the first receipt in this program where the gap
      between wiring and working has a behavioural consequence rather than a cosmetic one, and it
      belongs to whoever next touches the executor call path.

## 6. Deferred, not this change

- [ ] 6.1 The isolation flag/config shape admitting a workspace's own configuration while excluding
      the operator's host configuration. Gated on a measurement (proposal.md, design.md Non-Goals).
- [ ] 6.2 A push mechanism for workspace-side commits (proposal.md - What Changes; flagged, not
      solved).
- [ ] 6.3 Whether the agent's own workspace commits should ever carry a platform trailer.
      `commit-attribution`'s "written by the platform, never by the agent" rule, read literally,
      means they never will under this design — `turn.py` never itself commits into `places.workspace`
      (every `commit()` call in this change targets `places.queue`; see design.md), so there is no
      code path where the trailer could reach a workspace commit without either asking the agent to
      compose it (refused by that spec) or inventing a mechanism (a workspace-side platform commit)
      that has nothing left to commit once the agent's own commit already landed. Flagged as a real
      tension between "the workspace commit is what makes D014 machine-scoreable" and the existing
      trailer spec's scope, rather than resolved by guessing which one gives way.
