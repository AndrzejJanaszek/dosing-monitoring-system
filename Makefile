check: format-check lint typecheck imports test

format:
	uv run ruff format
	uv run ruff check --fix

format-check:
	uv run ruff format --check

lint:
	uv run ruff check

typecheck:
	uv run mypy

imports:
	uv run lint-imports

test:
	uv run pytest $(ARGS)

test-unit:
	uv run pytest -m unit $(ARGS)

test-integration:
	uv run pytest -m integration $(ARGS)

test-e2e:
	uv run pytest -m e2e $(ARGS)

coverage:
	uv run pytest --cov=dms --cov-report=term-missing $(ARGS)

.PHONY: check format format-check lint typecheck imports test test-unit test-integration test-e2e coverage
