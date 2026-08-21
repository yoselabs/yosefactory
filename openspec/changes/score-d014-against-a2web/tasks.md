## 1. Preflight — verify before acting (Article XII)

- [x] 1.1 Confirmed `ledger/spend.jsonl` at 14 rows (baseline) and yosefactory tree clean.
- [x] 1.2 Re-ran `make check` inside the container on a2web `fd24220` (not trusted from the
      archived report alone): `1893 passed, 2 deselected, coverage 92.14%`, $0, no agent.
- [x] 1.3 Confirmed `a2web-luh` still OPEN in `bd`; both named emission sites
      (`reddit.py` ~239, ~923) matched its description on read.
- [x] 1.4 Confirmed the hepsiburada item's commit (`fd24220`) is already on disk in a2web
      (`fix-hepsiburada-js-heavy-host`), so redoing it would have been make-work — this is why
      `a2web-luh` was picked instead.

## 2. Driver edit

- [x] 2.1 Edited `scripts/run_a2web_turn.py`'s `FRAME` to target `a2web-luh`.
- [x] 2.2 Bumped `owner`/`actor` to `yf-21`.
- [x] 2.3 **Added, found running turn 1**: `take_turn`'s own `isolated` kwarg defaults `True` and
      only feeds the `TurnRecord` field — separate from the `IsolationPolicy` actually handed to
      the executor. This driver never passed it, so turn 1's record read `"isolated": true` for a
      run that was `workspace_scoped` + `bypassPermissions` the whole time — the exact defect
      `cb2d2fa` fixed for `run_loop`'s own call site, unfixed here. Fixed:
      `isolated=policy.isolated`. Cheap (one line), in scope (this driver's own call), and
      necessary for the record to be honest — committed `da2fab7`.

## 3. The run — two live turns, both against exactly two mounts

- [x] 3.1 Confirmed image current (`4.97GB`, matching `ship-a2web-toolchain-as-a-stopgap`'s
      receipt).
- [x] 3.2 Ran `docker run --user 1000 -v …yosefactory:/app -v …a2web:/data/a2web …` directly (not
      `docker compose`, whose default service adds a third `.dev-workspace` mount) — exactly two
      mounts, twice. No board (`Places(publish_workspace=False, publish_queue=False)`, no
      `board.*` import — verified by reading the script before running). No push.
- [x] 3.3 Grep-counted the host's macOS user-home path prefix on turn 2's transcript: **1, not
      0.** Investigated rather than dismissed: the match is inside a captured `pytest` failure
      traceback, and the path belongs to a stale, host-compiled `__pycache__/*.pyc` under
      a2web's bind-mounted tree (`tests/capabilities/retrieval_completeness/__pycache__/*.pyc`,
      confirmed present and confirmed to embed the host path via `co_filename`) — bytecode
      compiled by an earlier host-side pytest run, imported unchanged by the container's pytest
      because its mtime still matched. **Caveat on the boundary-proof check, not an execution
      leak**: the grep-count is not a reliable sole proof of in-container execution when a shared
      bind-mounted repo carries pre-existing host-compiled cache. The separate `id`/`ls /Users`/
      `ls /data` boundary check (3.4) is unaffected and is the one that actually demonstrates the
      container's own reach.
- [x] 3.4 Boundary re-demonstrated against the rebuilt (stopgap) image: `id` → `uid=1000(factory)`;
      `ls /Users` → `No such file or directory`; `ls` on the operator's Knowledge repo path
      (outside both mounts) → `No such file or directory`; `ls /` → only the expected
      directories, no host paths; `ls /data` → `a2web` only.

## 4. The receipt

- [x] 4.1–4.3 See closing report — both `TurnRecord`s, the spend rows, and a2web's `git log` on
      `fix-reddit-archive-rescue-escalation` are quoted verbatim there.
- [x] 4.4 **`Yosefactory-Run` trailer confirmed absent** on the workspace commit (`9e183e4`) —
      only `Co-Authored-By: Claude Sonnet 5`. Design.md D2: **not fixed**, reported open. Fixing
      it means deciding who commits the workspace's own work (platform vs. agent) — architecture,
      not a line edit, and the same unresolved §6.3 tension `run-a-turn-against-a2web` and
      [[D014]]'s 2026-08-17 trail already named.

## 5. Close

- [x] 5.1 `openspec validate score-d014-against-a2web --strict` — see closing report.
- [x] 5.2 `make check` in yosefactory — see closing report.
- [x] 5.3 `git diff --cached` confirmed empty after every commit in this change (five commits:
      propose, isolated-fix, two item closeouts, spend row).
- [x] 5.4 **D014 is NOT satisfied by this run** — stated plainly in the closing report, from the
      ledger: both `TurnRecord`s read `"outcome": "failed"`. Turn 2's underlying a2web work is
      real and its gate passed, but the terminal `done` write to the queue was refused on a
      vocabulary defect, which is what the ledger — the authoritative scoring surface per
      [[D014]]'s 2026-08-17 ruling — actually shows.
- [x] 5.5 Five commits, each an explicit literal pathspec (`7ed1599`, `da2fab7`, `7e00d73`,
      `bd871ad`, `551419a`).
- [ ] 5.6 Archive.
