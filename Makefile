.PHONY: check lint fix ty test bootstrap

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
