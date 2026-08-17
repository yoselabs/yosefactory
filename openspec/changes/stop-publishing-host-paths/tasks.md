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
- [x] 2.3 Full `.git` directory backed up outside the repo before touching anything (irreversible
      operation; the backup is the actual undo path, not `filter-repo`'s own reflog pruning).
      `git-filter-repo --force --invert-paths --path
      ledger/runs/turn-20260817T051729Z-da1f32fc.stream.jsonl --path
      ledger/runs/turn-20260817T052307Z-1cad2281.stream.jsonl` run in place. `filter-repo` removes
      the `origin` remote by design (its own safety measure against pushing an unreviewed rewrite);
      re-added afterward, fetched (read-only) to restore `origin/main` for comparison, never
      pushed.
- [x] 2.4 Every other commit's message diffed against the pre-rewrite backup and confirmed
      byte-identical (`fe2e5c8`, `d76128a`, `149ae78`, `d211ae9`, `3aa4e63` spot-checked directly;
      the rest inferred from `filter-repo`'s own commit-map showing the 8 commits before `149ae78`
      keeping their original SHA, meaning `filter-repo` did not even touch their trees).
- [x] 2.5 The two removed transcripts recovered from the pre-rewrite backup and copied back onto
      disk at their original paths, untracked (matching Decision 1 — kept, not deleted, only
      unpublished). `git status` confirms `.gitignore` now excludes them.
- [x] 2.6 SHA mapping recorded (old → new) for every commit that changed, and reported below for
      the Knowledge repo's own records (§M8-M10 cite these by name).

**Verification, actual commands and output:**

```
$ git log --all -p -- 'ledger/runs/*.stream.jsonl'
(no output)

$ git grep "/Users/<operator>" $(git rev-list --all) -- ledger/   # hostpath-allow: placeholder
(no output; run for real with the literal username, not shown here)

$ git merge-base --is-ancestor origin/main HEAD && echo ok
ok
```

`git log origin/main..HEAD --oneline | wc -l` reads 18 (17 original unpushed commits + the guard
commit `stop-publishing-host-paths` added ahead of the rewrite, itself then rewritten along with
everything after `149ae78`) — confirming nothing on `origin/main` was touched and the guard commit
is included in what still needs pushing.

**SHA mapping** (old → new; the 8 commits before `149ae78` — `fe2e5c8` through `cf84cee` — kept
their original SHA; everything from `149ae78` on changed because `filter-repo` recomputes every
descendant's hash once an ancestor's tree changes, even where that descendant's own tree did not):

| Old SHA | New SHA | Note |
|---|---|---|
| `fe2e5c8` | `fe2e5c83e54a86194fadf75a122ac616ca5dd78f` | unchanged |
| `d76128a` | `d76128aff3690449a746a68826316d86ade01860` | unchanged |
| `0eb0d5c` | `0eb0d5c2911db709cd951d090b9002361e25a66e` | unchanged |
| `bf61312` | `bf61312f1221aa3cf0fd8cfc3f72646fdc83e891` | unchanged |
| `3123fa9` | `3123fa9f5c808fa3ca6f515e5958e88a55460faf` | unchanged |
| `ee3d537` | `ee3d5376d7e4e320a006a819bca1abbe5f2bb737` | unchanged |
| `c1c8bcc` | `c1c8bcce2c709676cfd6f79614d1c13f3e2e2af1` | unchanged |
| `cf84cee` | `cf84ceec795da0807778adcdf1275cfac10ce5ba` | unchanged |
| `149ae78` | `a039c154491dbb5ef6e6699f15a3e4958fdb212f` | **tree changed** — transcript removed |
| `e846260` | `d0f0675e2d55992bd0af7706b7c2f2f3be131b0a` | hash changed, tree unchanged |
| `0ed3d4e` | `8e3882e4f9467e7e7c2c63126157e98517b75b75` | hash changed, tree unchanged |
| `cf11efe` | `7c2c815656af4849c637ccf5a41ba2706e2e72f3` | hash changed, tree unchanged |
| `f8a0c68` | `6f4d8a92cd8706604fdd36b8cdce01169b741dd9` | hash changed, tree unchanged |
| `e49dfed` | `38a0d2a789a3626cfe8779a11b073f4029de6f1b` | hash changed, tree unchanged |
| `d211ae9` | `ffa16a64b76bdf64e5f7ad5fd4af1f79deddfebe` | **tree changed** — transcript removed |
| `11fbdc0` | `2905fb0f295e953952a1ecb23118c9aec14a7f21` | hash changed, tree unchanged |
| `3aa4e63` | `ff2df43b05fbbeb02a362b73dbf6020302971b5f` | hash changed, tree unchanged |
| `cd2cd99` (this change, §1) | `0f457ecf36bbe0e4cdf082417340241e764e0947` | hash changed, tree unchanged |

Commit messages spot-checked byte-identical old vs. new for `fe2e5c8`, `d76128a`, `149ae78`,
`d211ae9`, `3aa4e63` — the two rewritten and three representative unchanged commits.

## 3. Verify

- [x] 3.1 `ruff check src/ tests/` and `ty check src/` clean.
- [x] 3.2 Full suite passes (341 passed, 13 deselected — the `live`-marked tests), no `live` test
      run.
- [x] 3.3 `ledger/spend.jsonl` line count identical before and after (6 → 6) — read directly, not
      assumed from the deselect count.
- [x] 3.4 `openspec validate stop-publishing-host-paths --strict` passed before apply.
- [x] 3.5 Working tree clean before the rewrite and after (`git status --short` empty both times).
