## 1. Preflight — verify before acting (Article XII)

- [x] 1.1 Confirm `make` survived in the current `Dockerfile` and is on `PATH` for `factory`, not
      only present as root.
- [x] 1.2 Confirm a2web's HEAD (`fix-hepsiburada-js-heavy-host`) is still `fd24220` and its host
      `make check` still reads `1893 passed, 0 failed`.
- [x] 1.3 Confirm what patchright/zendriver actually need beyond the pip package — read a2web's own
      `Dockerfile` and `any_browser`'s zendriver backend for the real recipe, not an assumed
      package name.

## 2. Dockerfile change

- [x] 2.1 Add a `RUN` layer installing a2web's `[browser]` extra's system requirement
      (`patchright install --with-deps chromium`) as root, before the `USER factory` switch —
      root exists only in the build, per D023 §1.
- [x] 2.2 `PLAYWRIGHT_BROWSERS_PATH` set so zendriver's Chromium auto-discovery (which reads that
      env var, not a system Chrome) finds the same binary patchright baked.
- [x] 2.3 Comment block: stopgap, points at D023 §4, states the cost (image grows per project,
      finished the moment a second foreign repo needs a conflicting toolchain) and that this
      installs a2web's own declared `[browser]` extra, not a hand-picked package list.

## 3. Build and measure

- [x] 3.1 Record image size before (current `yosefactory-factory:latest`, if present) and after
      the rebuild.
- [x] 3.2 Build the image.

## 4. The receipt

- [x] 4.1 `docker run` as `factory` (uid 1000), a2web mounted at its own workspace path (matching
      the prior change's two-mount shape), `make check` invoked directly (no `take_turn`, no
      agent).
- [x] 4.2 Quote the result verbatim. Success = `1893 passed, 0 failed`, matching the host. A
      partial result (fewer failures, not zero) is reported as partial, naming the remainder.
- [x] 4.3 Inside the same invocation, demonstrate the boundary still holds — the container cannot
      read outside its declared mounts (same demonstration shape as the prior change's §4).

## 5. Close

- [x] 5.1 `ledger/spend.jsonl` row count before and after this change — must be unchanged (no
      `take_turn`, no agent invocation).
- [x] 5.2 `git diff --cached` confirmed empty after every commit.
- [x] 5.3 `openspec validate ship-a2web-toolchain-as-a-stopgap --strict`.
- [x] 5.4 `make check` in yosefactory stays green.
- [x] 5.5 Commit(s), each with an explicit literal pathspec.
- [x] 5.6 Archive.
