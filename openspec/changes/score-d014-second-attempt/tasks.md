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

- [x] 3.1 Confirmed image current (`6540a1fe0bd8`, `4.97GB`), matching the environment stopgap's
      own receipt.
- [x] 3.2 The run was launched via `docker run` direct (container `e8c2f54add9b`, found already
      in progress and let finish rather than duplicated — see trail below). Re-demonstrated the
      boundary explicitly afterward with a fresh `docker run --rm --user 1000 -v
      ~/Workspaces/yosefactory:/app -v ~/Workspaces/a2web:/data/a2web …`: `uid=1000(factory)`,
      exactly two mounts. Read `docker-compose.yml`'s `factory` service: its default `volumes:`
      is `./:/app` + `./.dev-workspace:/data/workspace` — two mounts of its own, neither of which
      is `/data/a2web` — so reaching this run's exact mount set via compose would require a third
      `-v` override on top of the service's own two, confirming the "compose adds a third mount"
      claim precisely rather than by assertion.
- [x] 3.3 Grep-counted the host's macOS user-home path prefix (`/Users/iorlas`) on the transcript
      (`ledger/runs/turn-20260821T082829Z-5e6dd1b8.stream.jsonl`): **0**, not 1. The prior run's
      stale-`.pyc` leak did not recur — nothing to investigate this time.
- [x] 3.4 Boundary re-demonstrated: `id` → `uid=1000(factory)`; `ls /Users` → no such file; `ls`
      on the operator's Knowledge repo path → no such file; `ls /` → only expected directories;
      `ls /data` → `a2web` only.

## 4. The receipt

- [x] 4.1 `TurnRecord` (`ledger/runs/20260821T082829Z-turn-20260821T082829Z-5e6dd1b8.json`):
      `run_id=turn-20260821T082829Z-5e6dd1b8`, `outcome=advanced`, `isolated=false`, `dirty=false`,
      `model=claude-sonnet-5`, `effort=medium`.
- [x] 4.2 Spend row joined by `run_id`: `{"ts": "2026-08-21T08:35:06.111893+00:00", "run_id":
      "turn-20260821T082829Z-5e6dd1b8", "total_cost_usd": 1.8582784500000007}` — 17th row.
- [x] 4.3 a2web `git log` on `a2web-qgo-primary-image`: `e778fd9 feat(ask): surface the page's own
      primary image URL (a2web-qgo)`, author `yosefactory <yosefactory@yoselabs.dev>`, no
      `Co-Authored-By` trailer this run (differs from prior runs, which carried
      `Co-Authored-By: Claude Opus/Sonnet 5` and no platform trailer either) — reported as
      observed, not investigated further; the `Yosefactory-Run` trailer gap itself remains the
      known, deliberately-unfixed D2 from `teach-the-done-event-schema`.
- [x] 4.4 The `done` event on `backlog/items/itm-20260821T082829Z-cc787b2f.jsonl` carries both
      `effects` (a full paragraph describing the change, the fallback order, the omission
      rationale, and the branch) and `verified_by` (`"make check (lint + ty + full pytest suite,
      coverage 92.15% >= 85% gate, plus the tach architecture/impact suite) passed clean..."`).
      **S990's fix held on a real, long, budget-pressured turn.**

## 5. Close

- [x] 5.1 `openspec validate score-d014-second-attempt --strict` — see closing report.
- [x] 5.2 `make check` in yosefactory — see closing report.
- [x] 5.3 `git diff --cached` confirmed empty after every commit in this change.
- [x] 5.4 **D014 is satisfied by this run** — from the ledger: `TurnRecord.outcome == "advanced"`,
      the first such outcome across all `score-d014-*` attempts. Stated in full in the closing
      report.
- [x] 5.5 Archive: this commit precedes the archive step, per Article XV.
