## Context

[[S989]] measured that the container's fixed image cannot satisfy a2web's own gate: 5 of a2web's
1893 own tests need its optional `[browser]` extra (`patchright` + `zendriver`), which the image
never installed. [[D023]] §4 authorises this as a named stopgap, not the design.

## What was actually needed, not assumed

Read before writing anything: a2web's own `Dockerfile` (which already bakes this same extra for its
own published image) and `any_browser`'s `zendriver.py` backend.

- `patchright` and `zendriver` are ordinary pip packages (`any-browser[patchright,zendriver]` is
  a2web's own extra), pinned to the exact versions a2web's `uv.lock` currently resolves —
  `patchright==1.60.1`, `zendriver==0.15.3` — read directly off a synced host `.venv`, not guessed.
- Neither ships a browser binary. `patchright install --with-deps chromium` bakes Chromium **and**
  the desktop system-lib tree (fonts, `libnss`, `libatk`, …) it needs to actually launch under a
  container — `install chromium` alone is not enough; a2web's own Dockerfile makes the same call.
- `zendriver` does not bring its own binary either. `any_browser.zendriver._resolve_executable`
  reads `PLAYWRIGHT_BROWSERS_PATH` and reuses whatever Chromium Patchright baked there — one bake
  serves both engines, confirmed by reading the vendor source, not assumed from the package names.
- Installed by `uv pip install --python /opt/venv <name>==<version>`, not folded into this repo's
  own `pyproject.toml`/`uv.lock` — these are a2web's dependencies, and yosefactory does not import
  either package.

## Why the shared `/opt/venv` matters

The image sets `UV_PROJECT_ENVIRONMENT=/opt/venv` globally (D3, `run-the-factory-in-a-container`).
`make check` inside a2web runs `uv run pytest …`, and `uv run` resolves against that same env
var rather than creating a project-local `.venv` under `/data/a2web` — a2web's own dependencies
already land in the shared venv this way (observed directly: `uv run` inside `/data/a2web` reported
"Installed 143 packages" against the shared env on first run). So installing `patchright`/
`zendriver` into `/opt/venv` — the same place a2web's own deps already go — is sufficient; no
separate a2web-scoped environment is needed for this stopgap.

## Receipt

```
  docker run --rm --user 1000 -v ~/Workspaces/a2web:/data/a2web -w /data/a2web \
    -e UV_PROJECT_ENVIRONMENT=/opt/venv -e PLAYWRIGHT_BROWSERS_PATH=/opt/browsers \
    yosefactory-factory:latest sh -c "make check"

  ================ 1893 passed, 2 deselected, 1 warning in 57.22s ================
  Required test coverage of 85% reached. Total coverage: 92.14%
```

Matches the host exactly (same command, same commit `fd24220`, same `1893 passed, 2 deselected`).
Zero remaining failures — not a partial result.

Boundary, re-demonstrated against the rebuilt image (a new artifact, not assumed to inherit the
prior image's isolation):

```
  id                                  -> uid=1000(factory) gid=1000(factory)
  cat <host CLAUDE.md path outside both mounts>  -> No such file or directory
  ls /Users                           -> cannot access '/Users': No such file or directory
  ls /data                            -> a2web   (only the intended mount)
```

## Image size

`yosefactory-factory:latest`: **2.16GB -> 4.97GB, +2.81GB.** The baked Chromium + its
`--with-deps` system-lib tree. This is the stopgap's price, per D023 §4, and it is recorded here
and in the `Dockerfile` comment next to the layer that costs it.

## Non-goals (restated from proposal.md)

Not the D023 vision (declaration-in-repo, build/run split, cache-key-by-declaration). Not touching
`verify.may_write_done` or any gate logic. Not modifying a2web — its `main` is untouched, its
current branch left exactly where it was found. No live `take_turn` in this change — the receipt
above is a direct `docker run`, $0, no agent invocation.

## Trail

- 2026-08-21 — built and measured by YF-20. `make` (added by `run-a-turn-against-a2web`) confirmed
  still on `PATH` for `factory` before any change was made (task 1.1). No spec touched
  (`skip_specs: true`) — `containerized-loop/dev-and-production`'s Docker-image requirement names
  `uv`/`claude`/`yosefactory`, not a foreign repository's own toolchain, so nothing it asserts
  changed.
