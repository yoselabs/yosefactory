## Why `should_plan` narrows to `claimed`/`doing` and not to something finer

Three candidate predicates were considered for "what counts as in flight, and therefore suppresses
planning":

1. **Unchanged: any non-terminal item.** This is S1021 itself — rejected on evidence, not argued.
2. **Any item with a live, unexpired bound** (`claimed`/`doing` via `expires_at`, `blocked` via a
   deadline read from its own `awaiting` or, for `kind: question`, from the linked question,
   `snoozed` via `scheduled_for`). This is the *nearest* fix to the original design intent — it
   would still prevent re-planning around a `blocked`/`snoozed` item for as long as its bound holds.
   Rejected for this change: nothing today reads `blocked`'s deadline or `snoozed`'s
   `scheduled_for` to fire a timeout (`eligible()`'s own docstring: "there is no sweeper"). Building
   that sweeper is a real, separate feature — cross-file reads for question-backed blocks,
   `on_timeout` policy dispatch (`escalate`/`default:`/`abandon:`), wiring `woke` for the first time
   ever — and is not required to stop the freeze this change exists to fix. Doing it anyway here
   risks exactly what Article VII warns against in the other direction: quietly growing a change
   past its dispatch.
3. **`claimed`/`doing` only.** Adopted. It is the smallest predicate that (a) stops the freeze for
   every one of the seven states S1021 names, and (b) keeps *some* meaning for "in flight" — a lease
   the reclaim sweep (this same change) guarantees cannot camp indefinitely, because it is reclaimed
   or poisoned within `Guardrails.wall_clock_seconds` of going stale, every turn.

**The paid-loop risk this creates, and why it does not need a new bound.** Once `failed` /
`falsified` / `needs_split` / `blocked` / `snoozed` stop suppressing planning, a backlog holding
only such items looks, to `should_plan`, exactly like an empty backlog: nothing ready, nothing
claimed/doing, plan. An empty backlog *already* triggers a planning turn on every wake — that is the
factory's normal steady state, not a new exposure — and it is already bounded by
`LoopBound.max_iterations` (mandatory, no infinite mode) and, on the unattended path,
`spend_ceiling_usd` (mandatory there too). A backlog with five stuck items and nothing ready costs
exactly what an empty backlog costs per turn: one planning invocation, capped the same way. The
qualitative change is: planning turns that used to be free (`nothing-ready`, no executor) now cost
money on a stuck-but-not-empty backlog, same as they already do on an empty one. This is named
explicitly rather than left to be discovered, per the dispatch's "must not burn money on a loop" —
the loop that constraint is actually aimed at is a *single item* retried without bound (next
section), not the existing, already-bounded planning cadence.

## The retry loop the attempt cap actually stops

Two independent ways an item could retry forever before this change, and how the attempt cap
(`Guardrails.max_attempts`) closes each:

1. **Lease crash-loop.** A turn claims an item, dies before writing anything to the item's own log
   (crash, OOM, CI kill). The next turn's reclaim sweep sees the expired lease and — before this
   change did not exist at all; the item just sat in `doing` forever. With reclaim alone (no cap),
   a container that reliably OOMs on this specific item would claim it, die, get reclaimed, claim
   it again, die again, forever — a free loop in wall-clock terms (each cycle costs at most one
   `wall_clock_seconds` of a dead process) but not in reviewer attention, and not free if the crash
   happens *after* spending tokens. The cap: `reclaim_expired` reads the same `attempt` the `claimed`
   event already carries (incremented on every claim, never reset); once it reaches
   `max_attempts`, the sweep appends `failed` (`retryable: false`, naming the exhausted lease) then
   `poisoned` instead of `reclaimed` — the item stops being `ready` and stops consuming turns.
2. **Explicit repeated failure.** An agent proposes `failed` against an item, the format already
   requires `attempt` and `retryable` on that event, and nothing before this change ever read
   either — an item could be claimed, fail, and (had anything moved it back to `ready`, which
   nothing currently does) fail again with no cap. This change reads both fields the moment a
   `failed` event lands: `retryable: false` poisons immediately regardless of attempt count (the
   agent's own judgment that retrying is pointless is taken at face value, once); `attempt >=
   max_attempts` poisons regardless of `retryable`. Either makes the item terminal and visibly
   named-stuck in its own log, rather than silently eligible for a claim that will never come
   (nothing claims a `failed` item today) or silently retried forever (had that changed later,
   unbounded).

**A third bug, found while wiring the cap, not designed around in advance: `attempt` could never
exceed 1.** `take_turn`'s claim step read `backlog.lease(target)` to compute the next `attempt` —
but `target` is always `ready` at the point it is claimed (`eligible()`'s own definition, and the
only way `pick()` selects anything), and `lease()` returns `None` for any state other than
`claimed`/`doing`. So every single claim, forever, computed `attempt = int(None-derived 0) + 1 = 1`
— the field the format has required since it was defined could never have recorded anything but 1
in production, no matter how many times an item was released or (now) reclaimed. Caught only because
a test that seeded an item mid-crash-loop and expected `attempt == 2` after a second claim failed
with `1 == 2`. Fixed by `backlog.claims()`, which counts every `claimed` event the item's whole
history carries rather than reading the most recent lease — a computation that survives the reset
`released`/`reclaimed` both perform by returning the item to `ready`, where `lease()` goes blind.
Named here because it directly gates the exhaustion cap this change adds: without it, `max_attempts`
was unreachable through the one code path meant to reach it.

`max_attempts` is a new `Guardrails` field, not a magic number inside `turn.py` — it is tuning
(moving it does not make an old record incomparable, `config.py`'s own docstring criterion),
defaulted like its four siblings (`window`, `wall_clock_seconds`, `turn_ceiling`,
`question_deadline_hours`) rather than chosen with traffic to learn from (D021's stated posture:
build the detector, learn the condition, decide the limit later).

## The commit-scoping bug, found wiring the reclaim sweep, and why it is fixed here rather than
## reported separately

`take_turn` calls `apply_answers(places.queue, actor=owner)` and discards the return value. Tracing
what that return value (`moved: list[str]`, the item ids `apply_answers` appended an `unblocked`
event to) is used for: nothing. Every `append()` writes to disk immediately (candidate file, folded,
renamed over the log) — that part is not in question, D002's append-only guarantee holds regardless
of what happens next. What happens next is `_finish`, the one place `commit()` is ever called, and
its `paths` argument is built from `touched` (the *target* item only) or `written` (planning's newly
created items) — never from whatever `apply_answers` touched. An `unblocked` item's new line is real
on disk and invisible to that turn's `git commit -- <paths>` (Article V's own form), which means:

- it is never pushed (a fresh clone of the queue, on another machine or the next scheduled run,
  would not see it — it exists only in this one working tree until *something* commits it, and
  nothing is arranged to)
- under `Places.local` (`places.queue == places.workspace`, every test fixture and today's only
  configuration), it is a real uncommitted change in the very tree `_finish`'s `tree_is_dirty` check
  reads to decide `TurnRecord.dirty` — so a turn that happened to unblock an unrelated item this same
  cycle would report `dirty: true` against *itself*, indistinguishable from the agent having left
  its own work half-finished.

This was found, not designed around in advance: it is the same shape of bug `_finish`'s own
`dirty`-then-spend-write ordering exists to prevent (`ADR-0011`), on a different code path nobody had
reason to look at until this change needed to add a second sweep step (`reclaim_expired`) sitting
right next to `apply_answers`. Wiring the new sweep correctly *requires* fixing this — both sweeps
return the paths they touched, and `take_turn` threads the combined list into whichever `_finish`
call ends the turn (the early `nothing-ready` return, the planning branch's `written`, and the
acting branch's `item_path`, via a new `extra_paths` parameter on `_dispose`). This is not a second,
self-assigned change riding along (Article VI) — it is the same function, the same commit-path
plumbing, touched because the new code sits in the identical position and would silently reproduce
the bug if left unfixed.

## What happens if a reclaimed lease's original turn is not actually dead

Assume two CI runners overlapping in wall-clock time, the scenario the dispatch names explicitly.
Turn A claims item X, its container stalls past `expires_at` but is not actually dead — it is slow,
not crashed. Turn B's reclaim sweep sees the expired lease and appends `reclaimed` (X → `ready`),
commits, and (if `places.publish_queue`) pushes. Turn A eventually finishes and tries to append its
own event (`done`, `failed`, whatever it decided) from the state it last read, `doing`.

- **`append()` itself never corrupts anything.** It folds the candidate against Turn A's *local*
  clone of the log, which — if Turn A never re-read the file after B's reclaim — still shows `doing`
  as the current state, so the fold succeeds locally and A writes a byte-identical-looking line to
  its own copy. No history is rewritten (D002 holds structurally: `append()` only ever adds lines).
- **The divergence surfaces at `push_repo`, not before.** `commit()` is a local `git commit`; nothing
  in `take_turn` pulls or rebases before it. When A's turn tries to `push_repo(places.queue)` and
  B's reclaim commit has already landed on `origin`, A's push is a non-fast-forward and
  `push_repo` returns `status: "rejected"` — today that only raises `PublicationFailed`, a
  `RuntimeWarning`, not an exception; A's own `TurnRecord` was already written locally as whatever
  outcome it computed, `ADVANCED` included, before `publish()` ever runs.
- **The net effect: a lost turn, not a corrupted item.** X's authoritative history (whatever
  reaches `origin`) is exactly what B wrote plus whatever the *next* successful claim writes — A's
  event never reaches it. A's own local ledger row claims a success the shared queue never receives.
  This is a real gap and this change does not close it: doing so needs either the compare-and-swap
  push `take_turn`'s own `cross_machine`/`cas_push` parameters already name and refuse
  (`"cross-machine operation needs the compare-and-swap claim push, which is not enabled"`) or a
  pull-rebase-retry loop around `push_repo` — both are a materially larger change than un-sticking
  the backlog, and the existing refusal already means this repository's only *supported* multi-writer
  path today is `cross_machine=False`, one queue clone per turn, protected by `single_flight` for the
  duration of that one turn. The reclaim sweep does not weaken that: it is exactly as safe, and
  exactly as exposed on the unsupported path, as every other writer already is. Named here rather
  than silently assumed away, per the dispatch's explicit ask — and worth a signal write-back
  (`build-loop.md`'s "During" trigger 3: a mechanism — the loud `PublicationFailed` — exists,
  fires silently, and nobody has looked at what it implies for queue-repo writes specifically until
  this change went looking).

## Why the loud-freeze fix is an exit code, not a new workflow

`stall.py` already does the hard part correctly (`run-guardrails/stall-detection`): it is invocable
standalone, reads only the durable record stream, and exits 0/1/2 by verdict. What is missing is a
caller. `runtime/loop.py`'s own docstring already states the position this change follows: a CI
workflow that has never fired is exactly what S195 catalogued nine of, so this repository builds the
runnable, observable mechanism and leaves the not-yet-built wrapper for a separate change. `main()`
(interactive) and `scheduled_main()` (the entrypoint `ops/launchd/dev.yosefactory.loop.plist.template`
already names as what a scheduler invokes) are that runnable mechanism today — wiring their exit
code to the stall verdict costs one function call and turns "nobody looks at stall.py" into "whatever
already invokes this entrypoint sees a red exit the moment it goes stale," with no new file, no new
schedule, no new secret.
