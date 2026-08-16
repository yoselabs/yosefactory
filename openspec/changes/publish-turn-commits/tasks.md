## 1. Push mechanics

- [x] 1.1 `PublishResult` (repo, status: pushed/skipped/rejected, detail) and `PublicationFailed`
      (a `RuntimeWarning` subclass) in `runtime/turn.py`.
- [x] 1.2 `_current_branch(repo)` — `git rev-parse --abbrev-ref HEAD`, `None` on detached HEAD.
- [x] 1.3 `_has_remote(repo, name="origin")` — `git remote get-url origin`, boolean.
- [x] 1.4 `push_repo(repo)` — explicit refspec `<branch>:<branch>`, no force, no tags; skip (not
      reject) when no remote or detached HEAD; classify a non-zero exit as `rejected`.

## 2. Wire publication into `take_turn`

- [x] 2.1 `publish(places, record)` — no-ops (returns `None`) unless `record.outcome is
      Outcome.ADVANCED`; otherwise pushes `places.workspace` then `places.queue`, in that order, and
      warns once per rejected push via `warnings.warn(..., PublicationFailed)`.
- [x] 2.2 Every `take_turn` return path (nothing-ready, planning, acting) calls `publish` on its
      record before returning it, unchanged, to the caller.

## 3. Tests

- [x] 3.1 A `bare_remote` fixture — `git init --bare` — usable as `origin` for either the `repo` or
      `workspace` fixture, entirely local, no network dependency.
- [x] 3.2 An advanced turn with `origin` configured on both places pushes both, workspace before
      queue (assert via the target refs on each bare remote, and via call order if needed).
- [x] 3.3 A turn with no remote configured on either place publishes nothing and raises no warning.
- [x] 3.4 A rejected push (bare remote pre-loaded with a commit the local branch does not have) warns
      via `PublicationFailed` and does not raise past `take_turn` — the record returned is unaffected.
- [x] 3.5 A `blocked` outcome and a `failed` outcome both publish nothing, asserted by the target
      branch being absent (or unchanged) on the bare remote after the turn.
- [x] 3.6 `make check` green.

## 4. What this does not prove

- [ ] 4.1 No test exercises a real network remote (GitHub, or any non-local `origin`) — every test
      uses a local bare repository. This proves the git plumbing and the outcome gate; it does not
      prove the platform can publish across an actual network boundary, with real auth and real
      latency. Consistent with [[S195]]: stated, not built, and not the first time this gap has been
      left for a receipt against the real thing.

## 5. Open, no owner

- [ ] 5.1 **A publication failure has no durable trace.** The turn record is committed before publish
      runs, and D002 plus turn-cycle's one-record-per-turn rule together mean nothing can retroactively
      amend it with what publication did. `warnings.warn` reaches whoever is watching the process in
      the moment and nobody who reads later — a ledger reader, a receipt, Denis checking D014 a week
      on. A publication failure nothing captures means D014 counts a commit nobody can see, which is
      the exact failure this change exists to fix, arriving through its own error path. Where a
      post-record event like this should live — the run stream, a separate publish log, something
      else — is a design question this change deliberately does not answer. Same shape as the
      planning-denial gap `raise-question-on-denial` left open. Not built here.
