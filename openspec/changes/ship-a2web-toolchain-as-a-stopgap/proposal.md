## Why

[[S989]] measured that the factory's fixed image cannot satisfy a foreign repository's own gate:
`run-a2web-turn` failed a2web's `make check` with `5 failed, 1888 passed` — confirmed, by controlled
host-vs-container comparison on the identical commit (`fd24220`), to be an environment gap, not a
defect in the change. [[D023]] §4 authorises a narrow stopgap: put a2web's missing toolchain into
this repo's own `Dockerfile`, labelled as a stopgap, while the real design (declaration-in-repo,
build/run split) is deliberately not built yet. [[D014]]'s window closes 2026-08-24.

## What Changes

- `Dockerfile` installs a2web's `[browser]` extra (`patchright` + `zendriver`, pulled through
  `any-browser[patchright,zendriver]`) and bakes the Chromium binary + its desktop system-lib tree
  patchright needs to launch it (`patchright install --with-deps chromium`), matching a2web's own
  Dockerfile's proven recipe for the same extra.
- `make` (already added by the prior change) is verified still present and on `PATH` for the
  `factory` user, not just baked into the image as root.
- The added layer is commented as a stopgap, pointing at [[D023]] §4, naming its cost (image grows
  per project; finished as a strategy the moment a second foreign repo needs a conflicting
  toolchain).
- Image size before/after is measured and put on the record.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
(none — `containerized-loop/dev-and-production`'s "Docker image" requirement names `uv`, the pinned
`claude` binary, and the `yosefactory` package; it does not enumerate a foreign repository's own
toolchain, so this addition does not change what that requirement asserts. `skip_specs: true`,
matching the prior change that added `make` to the same file for the same reason.)

## Impact

- `Dockerfile` — one new `RUN` layer (browser extra + Chromium bake), a `PATH`/`make` verification,
  and a stopgap comment block naming D023.
- Image size (recorded before/after in the closing report).
- No change to `runtime/`, `src/yosefactory/protocol/`, or any verification logic.

## Non-goals

- Not the D023 vision: no environment declaration in the workspace repo, no build/run phase split,
  no cache-key-by-declaration mechanism. Named here so this change is not mistaken for that one.
- Not touching the gate (`verify.may_write_done` or anything in `runtime/`) — the gate stays able to
  fail honestly, never taught to accept a baseline or skip a2web's tests.
- Not modifying a2web. Its `main` stays untouched; its current branch
  (`fix-hepsiburada-js-heavy-host`) is left exactly where it is.
- No live `take_turn` against a2web in this change — the receipt is `docker run ... make check`
  directly, not a platform turn. (Standing $5 allowance requested only if this assumption turns out
  wrong; expectation is $0.)
