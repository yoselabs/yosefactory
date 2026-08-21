## 1. Preflight — verify before acting (Article XII)

- [ ] 1.1 Confirm `ledger/spend.jsonl` row count (baseline) and yosefactory tree is clean.
- [ ] 1.2 Confirm the stopgap image's receipt still holds: `make check` inside the container on
      a2web `fd24220` still passes (re-check, do not trust the archived report alone).
- [ ] 1.3 Confirm a2web-luh is still OPEN in `bd` and its named files/lines still match its
      description.
- [ ] 1.4 Confirm the hepsiburada item's commit (`fd24220`) is genuinely already on disk in a2web,
      so redoing it would be make-work.

## 2. Driver edit

- [ ] 2.1 Edit `scripts/run_a2web_turn.py`'s `FRAME` to target `a2web-luh` (goal/method/assumptions,
      the two named emission sites, the acceptance criterion, "new branch, never main, do not
      push").
- [ ] 2.2 Bump `owner`/actor references to `yf-21`, leave everything else (Places, IsolationPolicy,
      Guardrails, test_command) unchanged.

## 3. The run

- [ ] 3.1 Build/confirm the image is current.
- [ ] 3.2 Run inside the container, exactly two mounts: yosefactory at `/app`, a2web at
      `/data/a2web`. No board, no push (verify by reading the script before running, not after).
- [ ] 3.3 Capture the transcript; grep-count the host's macOS user-home path prefix → must read `0`.
- [ ] 3.4 Re-demonstrate the boundary: attempt a read/write outside both mounts, record what
      happened.

## 4. The receipt

- [ ] 4.1 Quote the `TurnRecord` JSON verbatim: `run_id`, `outcome`, evidence queue/workspace were
      different repos.
- [ ] 4.2 Quote the matching `ledger/spend.jsonl` row, joined by `run_id`.
- [ ] 4.3 Quote a2web's `git log` on the produced branch — commit, author, trailers (or their
      absence, stated plainly).
- [ ] 4.4 State whether the `Yosefactory-Run` trailer is present on the workspace commit (expected:
      no — design.md D2) and whether it was fixed or left open.

## 5. Close

- [ ] 5.1 `openspec validate score-d014-against-a2web --strict`.
- [ ] 5.2 `make check` in yosefactory stays green.
- [ ] 5.3 `git diff --cached` confirmed empty after every commit.
- [ ] 5.4 State plainly whether D014 is satisfied, from the ledger.
- [ ] 5.5 Commit(s), each with an explicit literal pathspec.
- [ ] 5.6 Archive.
