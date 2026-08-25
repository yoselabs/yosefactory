.PHONY: check lint fix ty test test-live test-boardlive bootstrap guard guard-host-paths spell deps citations

check: lint ty test citations

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

# Drives real GitHub over `gh` against BOARD_REPO, a throwaway repo. COSTS NOTHING in model spend
# (no executor runs) but mutates external state and needs `gh` authenticated as the identity
# BOARD_REPO is visible to -- same exclusion principle as test-live, for a different resource.
# Run this before merging or releasing any change that touches src/yosefactory/board/ (S243: an
# excluded check that nobody runs is worse than no check -- it looks like coverage and provides
# none).
test-boardlive:
	@uv run pytest -q -m boardlive tests/board/

# Verifies no dependency resolves to a local shelf checkout instead of a pinned
# tag. Vacuous today (no shelf package is adopted yet) but wired ahead of one.
guard:
	@g=tools/hooks/forbid-local-shelf-source.py; \
	 [ -f "$$g" ] || g="$${SHELF_HOME:-../shelf}/tools/hooks/forbid-local-shelf-source.py"; \
	 [ -f "$$g" ] || g="$$HOME/Workspaces/shelf/tools/hooks/forbid-local-shelf-source.py"; \
	 if [ -f "$$g" ]; then python3 "$$g" --committed; \
	 else echo "guard: shelf clone not found (set SHELF_HOME) -- CANNOT VERIFY, not a pass" >&2; exit 2; fi

# This repository is public. Refuses the tip commit if it introduced a raw ledger transcript or an
# absolute host path (tools/hooks/forbid-host-paths.py). Wired as a prek hook too (fast, staged,
# every commit); this target is the same check run against what actually landed at HEAD, so a
# `--no-verify` commit is still caught the next time this runs.
guard-host-paths:
	@python3 tools/hooks/forbid-host-paths.py --committed

# typos in code, docstrings, and docs.
spell:
	uv run codespell src tests ledger workflows README.md CLAUDE.md

# dependency hygiene (unused / missing / transitive). Single-package repo, so
# this runs once from the root, unlike shelf's per-package packages/*/ loop.
deps:
	uv run deptry .

# Confirms every orchestration.md article id AGENTS.md cites still exists in K. Part of `check`
# (not the pre-commit hook) because K is routinely absent for other clones/CI, and a pre-commit
# hook that silently no-ops most of the time is the false-confidence shape this repo's own
# guidance warns against; `make check` is the more deliberate, rarer invocation where a skip is
# visible rather than assumed. Skips cleanly (exit 0) when K is not found -- that is not a failure.
citations:
	@python3 tools/hooks/check_orchestration_citations.py
