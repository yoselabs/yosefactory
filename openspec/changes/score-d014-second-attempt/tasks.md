## 1. Preflight — verify before acting (Article XII)

- [x] 1.1 Read `decisions/D014-*.md`, `D022-*.md`, `D023-*.md`, `signals/S989-*.md`, `S990-*.md`.
- [x] 1.2 Read both archived changes' `design.md` in full: `score-d014-against-a2web`,
      `teach-the-done-event-schema`. Did not inherit the first's diagnosis; the second's
      correction (distance-from-write, not absence) is what this run tests.
- [x] 1.3 Checked system date: 2026-08-21, confirming the dispatch's correction over the original
      dispatcher's belief. Window (2026-08-24) open.
- [x] 1.4 Read a2web state live: `fix-reddit-archive-rescue-escalation` at `9e183e4` (clean,
      `a2web-luh`'s real fix), `main` at `6f26e89` (untouched). `bd ready` read live (60 items).
- [x] 1.5 Confirmed `a2web-luh` and `a2web-cid` already committed — ruled out per dispatch.
      Found and ruled out a third stale-open bead in passing: `a2web-k5b` already fixed on `main`
      (`113579b`), not picked. Noted `a2web-1uh` also stale per dispatch's own hint.
- [x] 1.6 Picked `a2web-qgo` (fresh, bounded, single call site, ADR-governed) as the work item.
      Checked out a2web to clean `main` (`6f26e89`) on the host before the container run.
- [x] 1.7 Re-verified board-off and push-off by reading `scripts/run_a2web_turn.py` and grepping
      `runtime/turn.py`/`runtime/loop.py` for `board`/`Board` — no board mechanism reachable from
      `take_turn` at all.

## 2. Driver edit

- [x] 2.1 Edited `scripts/run_a2web_turn.py`'s `FRAME` to target `a2web-qgo`.
- [x] 2.2 Bumped `owner`/`actor` to `yf-23`.
- [x] 2.3 Set `cost_ceiling_usd=2.80`.

## 3. The run — exactly two mounts

- [ ] 3.1 Confirmed image current, matching the environment stopgap's own receipt.
- [ ] 3.2 Ran `docker run --user 1000 -v ~/Workspaces/yosefactory:/app -v ~/Workspaces/a2web:/data/
      a2web …` directly — not `docker compose` — and showed what compose would have added, to
      re-demonstrate the two-mount boundary explicitly.
- [ ] 3.3 Grep-counted the host's macOS user-home path prefix on the transcript. If non-zero,
      investigated — confirmed or refuted the prior run's stale-`.pyc` explanation, not assumed.
- [ ] 3.4 Boundary re-demonstrated: `id`, `ls /Users`, `ls` on the Knowledge repo path, `ls /`,
      `ls /data`.

## 4. The receipt

- [ ] 4.1 Quoted the `TurnRecord` verbatim: `run_id`, `outcome`, `isolated`, `dirty`, `model`,
      `effort`.
- [ ] 4.2 Quoted the joined spend row from `ledger/spend.jsonl`.
- [ ] 4.3 Quoted a2web's `git log` on the produced branch (commit, author, trailers).
- [ ] 4.4 Stated plainly whether the `done` event carried `effects` this time (S990 measurement,
      independent of D014's outcome).

## 5. Close

- [ ] 5.1 `openspec validate score-d014-second-attempt --strict`.
- [ ] 5.2 `make check` in yosefactory.
- [ ] 5.3 `git diff --cached` confirmed empty after every commit in this change.
- [ ] 5.4 Stated plainly, from the ledger: is D014 satisfied by this run.
- [ ] 5.5 Archive.
