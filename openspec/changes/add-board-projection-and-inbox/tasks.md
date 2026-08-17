## 1. Read and re-acquire, verify before building

- [x] 1.1 architecture.md §7, orchestration.md, `_night-run-2026-08-16.md` §M8/§M9, S987, S194,
      S195, `backlog-item-format/spec.md`, `runtime/turn.py`, `runtime/loop.py` — read in full
- [x] 1.2 Verified `priority_set`, `cancelled`, `answered` each have a live production reader
      before building `ingest()` on top (design.md, "Verified before building on it") — `answered`
      is fully wired (`apply_answers()`, called every turn); `priority_set`/`cancelled` are
      reachable through the generic single-event apply path, not S195-dead
- [x] 1.3 Credentials and repo choice surfaced to the director in the first third; throwaway
      private repo `iorlas/yosefactory-board-receipt` created, `gh` calls bounded to it explicitly

## 2. The adapter interface and the fake

- [x] 2.1 `src/yosefactory/board/event.py` — `Event` dataclass, command-text parser
      (`/priority N`, `/answer <text>`, `/cancel <reason>`)
- [x] 2.2 `src/yosefactory/board/adapter.py` — `BoardAdapter` Protocol (5 methods only)
- [x] 2.3 `tests/board/fake_adapter.py` — in-memory adapter for unit tests, same Protocol

## 3. Projection (git → board)

- [x] 3.1 `src/yosefactory/board/projection.py` — `project_all(repo, adapter)`: read every
      backlog item, `open()` (idempotent, marker-search, no cache), `project()`, `close()` if
      terminal
- [x] 3.2 Unit tests against the fake adapter: re-running `project_all()` twice does not create a
      second thread for the same item; a terminal item gets `close()` called once

## 4. Command inbox (board → git)

- [x] 4.1 `src/yosefactory/board/inbox.py` — `ingest(repo, adapter, actor)`: read
      `list_events(since)`, apply each via `runtime.turn.append()`, record to
      `ledger/board/consumed.jsonl`
- [x] 4.2 Idempotency: unit test — same event_id ingested twice, target log gains one line, not two
- [x] 4.3 Rejection: unit test — unknown item id, illegal transition, malformed payload each
      produce a `comment()` call naming the reason and a `rejected` consumed-log line; one bad
      command in a batch does not stop the rest

## 5. GitHub Issues adapter

- [x] 5.1 `src/yosefactory/board/github.py` — `GitHubIssuesAdapter`, `gh` subprocess calls,
      `--repo` explicit on every call, marker-based `open()`
- [x] 5.2 Command comment parsing wired into `list_events()`; non-command comments ignored

## 6. The re-projection acid test — the deliverable

- [x] 6.1 New pytest marker `boardlive` (pyproject.toml), excluded from default `addopts`, run
      explicitly — distinguished from `live` because it costs $0 in model spend but touches a real
      external repo
- [x] 6.2 `tests/board/test_reprojection.py`: populate `iorlas/yosefactory-board-receipt` from real
      git items, snapshot (item id, title, state), delete every issue, re-run `project_all()`,
      snapshot again, assert equal
- [x] 6.3 Run for real, read the result from the GitHub API (not from `project_all()`'s own return
      value) — quoted verbatim in the closing report

## 7. Close

- [x] 7.1 `openspec validate add-board-projection-and-inbox --strict`
- [x] 7.2 `make check` — confirm still $0, `ledger/spend.jsonl` unchanged
- [x] 7.3 Commit: change directory + `src/yosefactory/board/` + `tests/board/` + `pyproject.toml`
      — explicit literal pathspecs, `-F <message-file>`, `PREK_ALLOW_NO_CONFIG=1`,
      `git diff --cached` confirmed empty after
- [x] 7.4 Archive; `openspec validate --specs --strict`
- [x] 7.5 Report to director: commits, `make check` $0 proof, the acid-test receipt quoted from
      disk, what a rejected command looks like on Denis's phone, the credential ask, anything
      contradicting the dispatch
