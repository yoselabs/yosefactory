.PHONY: check lint fix ty test bootstrap guard spell deps

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

test:
	@uv run pytest -q

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
