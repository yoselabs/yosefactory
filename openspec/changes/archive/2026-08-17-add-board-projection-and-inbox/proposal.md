# add-board-projection-and-inbox

Promotion: architecture.md §7, "The board: authoritative for nothing" — v2's repair to v1's
two-master-by-field board, adversarially reviewed and settled before this change existed. This
change implements the slice §7 names as buildable now: **projection + command inbox + consumer
offset + the re-projection test**, GitHub Issues as the first adapter.

## Why

Denis, from his phone, PC offline: *"find something, see situation, type something and send it."*
Nothing in this repo lets him do that today — `apply_answers()` in `runtime/turn.py` already names
the gap in its own docstring: *"No steering inbox is read: no such format exists in this
repository... Recorded as a gap rather than invented."* This change invents it.

§7's acid test, restated as the thing this change must survive rather than merely pass once: *"if
the whole board can be deleted and re-projected from git, it is a read model; if not, it is a
second master."* The test is run for real in this change — a populated board destroyed and
re-projected, compared on disk — not assumed from the code reading correctly.

## What Changes

- **New module `src/yosefactory/board/`** — `Event`, `BoardAdapter` (Protocol: `list_events`,
  `open`, `project`, `comment`, `close`), a GitHub Issues adapter, and two functions:
  `project_all()` (git → board mirror) and `ingest()` (board commands → git events).
- **The board is authoritative for nothing.** `project_all()` only ever reads `backlog.items()`
  and writes to the adapter; nothing reads the adapter to decide anything. `ingest()` is the one
  place a board read happens, and what it does with a read is *append a git event* — never branch
  a decision on the board's own state.
- **Commands reuse the vocabulary that already exists.** A `set_priority` command appends
  `priority_set` (already legal on any non-terminal item — `backlog.py`); a `cancel` command
  appends `cancelled`; an `answer` command appends `answered` to the named question
  (`question.py`). No new event types anywhere in `protocol/`. The board adds a transport, not a
  vocabulary.
- **Idempotent by `event_id`.** A durable, append-only `ledger/board/consumed.jsonl` records every
  board event `ingest()` has applied; re-running `ingest()` against the same `since` window is a
  no-op for anything already there. That file's own fold, not a separate pointer, is the consumer
  offset.
- **Rejection is visible, never silent.** A command that names an item or question that does not
  exist, or that the fold refuses (illegal transition, bad payload), gets a reply comment on the
  same GitHub thread saying so — concretely, what Denis sees on his phone under Article XVI's
  receipt question.
- **Re-projection is a real, runnable check**, not a claim: `tests/board/test_reprojection.py`
  (marked `boardlive`, excluded from `make check`, run explicitly) populates a private throwaway
  repo, destroys every issue in it, re-projects from the same git items, and asserts the
  (item id, title, state) triples match.

## Non-goals

Named explicitly so they are not silently missing:

- **Loop-to-loop messaging and the `GITHUB_TOKEN` echo hazard** (architecture.md §7, "The hazard
  the board actually carries"). That is Denis-to-loop's harder cousin — a different actor guard, a
  different addressing problem — and not this change.
- **Forgejo.** Named as the second implementation in architecture.md §7; the interface
  (`list_events`/`open`/`project`/`comment`/`close`) is written so it does not become impossible,
  but nothing here builds it.
- **The bounded open-items index** (architecture.md §10's O(history) read cost). `project_all()`
  reads every item on every run, same as `runtime.turn.items()` already does; the bound is a named,
  separate debt, not solved here.
- **Wiring `ingest()`/`project_all()` into `take_turn` or `run_loop` by default.** Both are
  standalone, callable functions — analogous to `apply_answers()`, which `take_turn` already calls
  unconditionally today. Whether the board sits inside every turn, on its own schedule, or behind
  a flag is a deployment decision for the next change, not this one. `render_loop.md`/`design.md`
  in this change name the shape; nothing here changes `runtime/turn.py` or `runtime/loop.py`.
- **A production credential.** The receipt runs on `gh`'s already-authenticated local session
  against a private throwaway repo. What a container/scheduled deployment needs (a scoped PAT,
  reaching the container via `.env`) is named in this change's design and left for Denis to
  provision — never built, requested, or assumed here.

## Capabilities

### New Capabilities

- `board-projection/inbox`: a read-only git→board projection that survives full deletion and
  re-projection, and an append-only, idempotent command inbox that turns board-side priority
  changes, answers, and cancellations into ordinary backlog/question events — with every rejection
  visible on the same thread it arrived on.

## Impact

- `src/yosefactory/board/__init__.py`, `event.py`, `adapter.py`, `github.py`, `projection.py`,
  `inbox.py` — new.
- `tests/board/` — new: adapter-protocol tests against a fake in-memory adapter (command parsing,
  idempotency, rejection), and one `boardlive`-marked test against a real private repo (the
  re-projection acid test).
- `pyproject.toml` — new pytest marker `boardlive`, excluded from default `addopts` alongside the
  existing `live` marker; distinguished from it because a `boardlive` test costs $0 in model spend
  (S987/S194's distinction: money spent vs. network/credentials touched) but does mutate a real
  external repo, which `make check` must never do on an unconfigured machine.
- No changes to `runtime/turn.py`, `runtime/loop.py`, or any existing `openspec/specs/` capability.

## The receipt question (Article XVI)

**What would distinguish built from works:** populate a real board from real git items, delete
every issue, re-project, and diff the two snapshots read from the GitHub API — not from this
module's own return values. If projection silently depended on a cached mapping rather than git
alone, the second pass would either fail to find the deleted issues (and duplicate) or produce a
different set from the first. The test is written to catch exactly that.
