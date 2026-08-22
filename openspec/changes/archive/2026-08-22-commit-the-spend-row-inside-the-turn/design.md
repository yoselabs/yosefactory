## The sequencing problem, stated precisely

The cost is not known until the executor returns. The commit that must carry it is the same commit
`_finish` already writes for the run record — the one produced strictly *after* the executor
returns. Naively, that looks free: just write the row somewhere before that commit runs. It is not
free, for two independent reasons, both found by running the tests rather than by reasoning ahead of
them.

### Reason one: the "done" gate reads the tree before the commit runs

`verify.may_write_done` (`tree_clean`) requires `places.workspace` to have **zero** uncommitted
changes before a `done` proposal can pass — no ignore list, unlike the supervisor's own
`tree_is_dirty`. Under `Places.local` (today's only configuration; every test fixture), `places.
queue` and `places.workspace` are literally the same directory. An early version of this change
called `spend.record()` at the top of `_dispose`, before any gate ran. Two tests failed immediately:

```
AssertionError: assert <Outcome.FAILED> is <Outcome.ADVANCED>
note: "... working tree has 1 uncommitted change(s)"
```

The write itself — an untracked `ledger/spend.jsonl` sitting in the tree `tree_clean` was about to
inspect — was the uncommitted change. This is not a hypothetical the dispatch was hedging about; it
reproduces on the very first two tests that exercise a `done` proposal.

**Fix:** every write this change makes happens inside `_finish`, and `_finish` is reached, on every
path, strictly *after* whatever gate that path's event required. The "done" branch in `_dispose`
already enforces this ordering for its own writes (the item's `append()`, the workspace delivery);
this change's write joins that same discipline rather than inventing a second one.

### Reason two: `_finish`'s own `dirty` flag reads the tree too

Not only the gate. `_finish` computes `TurnRecord.dirty` via `tree_is_dirty(places.workspace,
ignore=runs_dir)` — and `spend.jsonl` lives in `places.ledger.parent`, a **sibling** of `runs_dir`,
not inside it, so the `ignore` argument does not cover it. Had the spend write happened before this
line, under `Places.local` it would make every turn that spends anything at all report `dirty=true`
against itself — a self-inflicted false positive on the one field this platform relies on to tell
"the agent left work half-done" from "the platform's own bookkeeping is still landing."

**Fix:** `_finish` computes `dirty` first, then writes the spend row. The run record's own
`dirty` field is therefore computed before any of `_finish`'s own writes touch the tree — the same
ordering principle applied a second time, inside a single function instead of across `_dispose`'s
branches.

### Why not simply move `record()` earlier, as one might reflexively try

The dispatch names this option and rejects it correctly: the number does not exist before the
executor returns. What *is* available earlier is nothing — there is no sequencing rescue on that
side. The only real design space is *where, relative to the gate and to `dirty`, the write happens
after the cost is known* — which is what the two reasons above answer.

### Why not "defer the run-record commit until after the executor returns"

Already true, and was true before this change: `_finish`'s `commit()` call is only ever reached
after `executor(...)` has returned in `take_turn`. There was no earlier commit to defer — the actual
defect was narrower than that framing suggests: the commit was correctly late, but its pathspec
list never named the spend row, and the row itself was written to the wrong repository entirely
(see "Why `SPEND_LOG`'s resolution needed to change" below).

## Failure paths

Three, matching the dispatch's own enumeration, and the priority order the dispatch states directly:
**the agent's delivered commit outranks the ledger record, which outranks the spend row.**

### The executor throws before returning

`take_turn`'s call to `executor(...)` is unguarded — an exception propagates out of `take_turn`
entirely. `_dispose`/`_finish` never run: no run record, no spend row, no item transition this turn.
This is pre-existing behaviour, unrelated to this change (the `claim` commit made *before* the
executor ran already persisted, so the item reads as claimed-and-abandoned rather than untouched —
exactly the state the code around `commit(places.queue, [item_path], f"claim(...)"...)` was already
built to leave legible). Nothing here widens or narrows that.

### `commit()` itself fails (the git operation in `_finish`)

`commit()`'s existing failure path applies unchanged: `git commit` is attempted, and on refusal the
index is restored and `TurnError` is raised, propagating out of `_finish`/`_dispose`/`take_turn`.
Because the write to `spend.jsonl` already happened (this function's earlier step) and the file may
or may not have been previously tracked, a failed commit here means the run record *and* the spend
row both fail to land in this commit together — which is correct: they are one transaction by
design, so they fail together rather than one silently landing without the other. Crucially, this
failure is **downstream of** `_deliver_workspace`, which already ran (for a `done` proposal) and
already persisted the agent's own commit as a separate git operation in a different repository under
cross-repo operation, or an earlier point in the same repository under `Places.local` — either way,
already durable before this function was ever reached. The agent's delivered work is not put at risk
by this function's own failure.

### The spend write itself fails (disk full, permission denied, `OSError`)

Caught explicitly, inside `_finish`, and never allowed to propagate. The turn's `note` gains one
clause (`"... [spend row not recorded: <reason>]"`); the run record, the item transition, and (for a
`done` proposal) the workspace delivery all proceed exactly as they would have. `commit()`'s own
pathspec filtering (`present = [p for p in paths if p.exists()]`) means a spend log that was never
successfully written is simply absent from that commit's diff — not an error, not a partial file.

## Why `SPEND_LOG`'s resolution needed to change (for real turns)

`runtime.spend.SPEND_LOG` resolves via `paths.repo_root()`, which walks up from `spend.py`'s own
`__file__` to the nearest `pyproject.toml`/`.git` — deliberately the platform's own **installed**
location, stated explicitly in that module's docstring: "spend belongs to the platform that paid,
not the repository worked on." That reasoning is still correct in spirit. What has changed since it
was written is that "the platform" now has two distinct notions that used to coincide:

- **Where the package is installed** (`repo_root()`) — `/app` in the container
  (`run-the-loop-inside-the-container`'s own Dockerfile, `COPY . .` as root, never `chown`'d to
  uid 1000; ADR-0007 only fixes the venv and browsers, not `/app` itself).
- **`places.queue`** — the repository `turn.commit()` actually stages and commits into. Under the
  container's own `docker-compose.yml`, this is a **separate** bind mount (`/data/workspace`),
  deliberately not `/app` (D1, "the mount race").

These were the same directory under every configuration this platform ran before
`run-the-loop-inside-the-container` existed, so the distinction was invisible. It is not invisible
now: a row written to `repo_root()` can never be staged by a `commit()` scoped to `places.queue`
when the two diverge, regardless of how carefully the pathspec list is built. Renaming or moving
`SPEND_LOG` does not fix this — no *fixed* path fixes it, because the correct location is a property
of which `Places` a given turn is running against, not a constant.

**Decision:** every caller that actually runs a turn (`turn._finish`, `loop.run_loop`'s own
spend-ceiling check) resolves the spend log from `places` (`spend_log_for(places)`), not from
`SPEND_LOG`. `SPEND_LOG` itself is kept, unchanged, as `spend.record`/`spend.total_since`'s default
— it is still exactly correct for a caller with no `Places` in view: a direct import, a REPL, or
`tests/conftest.py`'s own `make test-live` session receipt, where "the platform's own checkout" and
"the repository being worked" are one and the same directory by construction. Changing the default
itself, rather than what real turns pass, would have broken that one remaining correct caller for no
gain — `spend_log_for` is additive, not a replacement.

This also happens to relocate every future real spend row out of the uid-1000-cannot-write-`/app`
problem, as a side effect of fixing the actual defect rather than as its target: `places.queue` is
never `/app` under the container's own topology, so a row that used to be unwritable now lands
somewhere uid 1000 already has to be able to write for the run record to land at all. The permission
defect itself — `/app` not being `chown`'d — is untouched and is not this change's to fix (see
Non-goals in `proposal.md`).

## The receipt this change is chasing

Not "the file exists on disk" — `runtime/spend.py`'s own tests already covered that, and it is
exactly the instrument-not-subject failure (K signal S194) the dispatch names directly. The receipt
is: **after a turn that spent money, the spend row for that `run_id` is present in `git show HEAD`**
— committed, not merely written — proven by reading the committed blob back out of git, not by
`Path.exists()`. See `tasks.md` §5 for the test that asserts exactly this.

## Revisit trigger, stated once and carried into the ADR

If `Places.queue` and `Places.workspace` are ever split under a configuration this change did not
consider (multiple queues sharing one workspace, or vice versa) such that `spend_log_for`'s
`places.ledger.parent` stops being a repository `commit()` can actually reach, this ordering and
resolution need re-examination — not a symptom of this change being wrong, a symptom of `Places`
growing a shape it did not have in 2026-08-22.
