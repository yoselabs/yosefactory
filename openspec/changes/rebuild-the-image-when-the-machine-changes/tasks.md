## 1. Derivation

- [x] 1.1 Enumerate git-tracked files vs `.dockerignore` mechanically; confirm what actually
      enters the image via `COPY . .`. Result: 451 tracked, 0 excluded — captured in design.md.
- [x] 1.2 Measure the last real push build's wall-clock and step timings
      (`gh run view <run-id> --log`) to price a cached rebuild honestly.
- [x] 1.3 Confirm GitHub Actions minute cost for a public repo on standard runners
      (fetched from `github.com/pricing`, not assumed).

## 2. Workflow fix

- [x] 2.1 `.github/workflows/publish-image.yml` — remove the `paths:` filter from the `push:`
      trigger; keep `workflow_dispatch`.
- [x] 2.2 `actionlint` clean on the changed workflow file.

## 3. ADR supersession

- [x] 3.1 `decisions/0010-image-publish-trigger-tags-and-provenance.md` — `Superseded by:` updated
      to point at the new ADR; Decision 1 annotated in place (not deleted) with a pointer.
- [x] 3.2 New `decisions/0013-*.md` — records the trigger change, the mechanical derivation, the
      measured cost, and evaluates whether ADR-0010's own `Revisit trigger:` named this case (it
      did — say so).

## 4. Staleness detection — decide, don't silently skip

- [x] 4.1 Decide whether this repo should carry a staleness detector, given the constraint that it
      must not depend on `factory-state` (private) and must not be a check that passes by
      describing itself.
- [x] 4.2 Record the decision and its reasoning in design.md regardless of outcome (built here /
      belongs elsewhere / not needed given what already exists).

## 5. Verification

- [x] 5.1 `make check` — green. **Does not prove the trigger fires correctly**; a workflow trigger
      is exercised only by a real push to GitHub. State this plainly in the closing report — not
      as a caveat, as the actual proof status.
- [x] 5.2 `openspec validate rebuild-the-image-when-the-machine-changes --strict` passes.
- [x] 5.3 `python3 tools/hooks/forbid-host-paths.py` clean over changed files (public repo).
