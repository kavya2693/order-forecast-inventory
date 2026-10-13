.PHONY: data run check test lint fmt

data:
	uv run python scripts/generate_data.py

run:
	uv run order-forecast --refresh

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

fmt:
	uv run ruff format .
	uv run ruff check --fix .

test:
	uv run pytest -q

check: lint test
