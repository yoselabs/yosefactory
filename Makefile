.PHONY: lint lint-harness lint-jscpd lint-actions fix test check coverage-diff security-audit arch bootstrap similar

lint: lint-harness lint-jscpd

lint-harness:
	agent-harness lint

lint-jscpd:
	pnpm lint:jscpd

fix:
	agent-harness fix

test:
	uv run pytest tests/ -n auto -m "not serial" --cov=a2sdlc --cov-report=xml --cov-report=term-missing
	uv run pytest tests/ -m "serial" --cov=a2sdlc --cov-report=xml --cov-report=term-missing --cov-append || [ $$? -eq 5 ]

coverage-diff:
	@uv run diff-cover coverage.xml --compare-branch=main --fail-under=95

security-audit:
	agent-harness security-audit

arch:
	@uv run lint-imports

check: lint arch test coverage-diff security-audit

bootstrap: ## First-time setup after clone
	uv sync
	agent-harness init --apply
	@if command -v prek >/dev/null; then prek install; \
	elif command -v pre-commit >/dev/null; then pre-commit install; \
	else echo "Install prek (brew install prek) or pre-commit for git hooks"; fi
	@echo "Done. Run 'make check' to verify."
