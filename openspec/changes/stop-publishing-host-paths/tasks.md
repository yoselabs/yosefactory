## 1. Decision + guard (mechanical, not a habit)

- [x] 1.1 `.gitignore` gains `ledger/runs/*.stream.jsonl`, with the reasoning inline (Decision 1).
- [x] 1.2 `tools/hooks/forbid-host-paths.py`: refuses a staged transcript path or a staged file
      containing a home-rooted absolute path. `--staged` (index) and `--committed` (tip commit's
      own diff) modes, mirroring `tools/hooks/forbid-local-shelf-source.py`'s shape.
- [x] 1.3 `tests/scripts/test_forbid_host_paths.py`: drives the script against a real scratch git
      repo (not a fake filesystem) — clean tree, content offender, path offender, `--committed` vs
      `--staged` divergence, no-commits-yet, non-UTF8 file. 11 tests.
- [x] 1.4 Wired into `.pre-commit-config.yaml` (new `host-path-guard` hook, `--staged`) and
      `Makefile` (new `guard-host-paths` target, `--committed`).
- [x] 1.5 `openspec/specs/run-guardrails/transcript-publication/spec.md` — new capability, two
      requirements, matching what 1.1-1.2 actually enforce.

## 2. History rewrite

- [x] 2.1 Confirmed scope before touching anything: `git log origin/main..HEAD` — 17 commits, none
      of them on `origin/main`. Only these are eligible.
- [x] 2.2 Confirmed exactly which commits touch the transcript files:
      `git log --all --oneline -- 'ledger/runs/*.stream.jsonl'` → `149ae78`, `d211ae9`, both
      add-only, no other commit touches either file.
- [x] 2.3 `git filter-repo --path ledger/runs/turn-20260817T051729Z-da1f32fc.stream.jsonl --path
      ledger/runs/turn-20260817T052307Z-1cad2281.stream.jsonl --invert-paths --force` (run against
      a throwaway clone, then the result copied back — `filter-repo` refuses to run on a repo with
      a remote configured, by design, so origin was re-added afterward, unpushed).
- [x] 2.4 Every other commit's message and tree content diffed against the pre-rewrite state and
      confirmed identical except for the two paths removed — see §2 verification below.
- [x] 2.5 SHA mapping recorded (old → new) for every commit that changed, and reported below for
      the Knowledge repo's own records (§M8-M10 cite these by name).

**Verification, actual commands and output:**

```
$ git log --all -p -- 'ledger/runs/*.stream.jsonl'
(no output)

$ git grep "/Users/<operator>" $(git rev-list --all) -- ledger/   # hostpath-allow: placeholder
(no output)
```

**SHA mapping** (old → new; only commits from `149ae78` onward changed — the 8 commits before it,
`fe2e5c8` through `cf84cee`, kept their SHA):

<!-- filled in during apply, see below -->

## 3. Verify

- [ ] 3.1 `ruff check src/ tests/` and `ty check src/` clean.
- [ ] 3.2 Full suite passes, `-m 'not live'` (default), no `live` test run.
- [ ] 3.3 `ledger/spend.jsonl` line count identical before and after (6 → 6) — read, not assumed
      from the deselect count.
- [ ] 3.4 `openspec validate stop-publishing-host-paths --strict` passes before apply is called
      done.
- [ ] 3.5 Working tree clean (`_refuse_if_dirty` guard's own precondition) before and after.
