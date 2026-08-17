.PHONY: check lint fix ty test test-live bootstrap guard spell deps

check: lint ty test

bootstrap:
	@uv sync --all-extras

lint:
	@uv run ruff check src/ tests/

fix:
	@uv run ruff check --fix src/ tests/
	@uv run ruff format src/ tests/

ty:
	@uv run ty check src/

# Excludes `live`-marked tests (pyproject.toml addopts: `-m 'not live'`), so `check`/`test` never
# reach the real pinned `claude` binary and never bill money -- even repeatedly across a dev loop.
# This is deliberate, not an oversight: recording spend (see `test-live` below) does not fix a
# default that bills on every iteration, only removing live tests from the default path does.
test:
	@uv run pytest -q

# Drives the real pinned `claude` binary. COSTS REAL MONEY, one invocation per test. Run
# deliberately, not as part of `check`. Every run appends a row to `ledger/spend.jsonl`
# (see runtime/spend.py) and this target prints the session's total spend when it finishes.
test-live:
	@uv run pytest -q -m live

# Verifies no dependency resolves to a local shelf checkout instead of a pinned
# tag. Vacuous today (no shelf package is adopted yet) but wired ahead of one.
guard:
	@g=tools/hooks/forbid-local-shelf-source.py; \
	 [ -f "$$g" ] || g="$${SHELF_HOME:-../shelf}/tools/hooks/forbid-local-shelf-source.py"; \
	 [ -f "$$g" ] || g="$$HOME/Workspaces/shelf/tools/hooks/forbid-local-shelf-source.py"; \
	 if [ -f "$$g" ]; then python3 "$$g" --committed; \
	 else echo "guard: shelf clone not found (set SHELF_HOME) -- CANNOT VERIFY, not a pass" >&2; exit 2; fi

# typos in code, docstrings, and docs.
spell:
	uv run codespell src tests ledger workflows README.md CLAUDE.md

# dependency hygiene (unused / missing / transitive). Single-package repo, so
# this runs once from the root, unlike shelf's per-package packages/*/ loop.
deps:
	uv run deptry .
