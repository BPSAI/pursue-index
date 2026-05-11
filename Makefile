.PHONY: install install-dev scrape-inspect scrape download ocr ingest serve \
        test lint typecheck fmt db-up db-down clean

# ---- setup ----
install:
	uv venv && . .venv/bin/activate && uv pip install -e .

install-dev:
	uv venv && . .venv/bin/activate && uv pip install -e ".[dev]"

# ---- pipeline shortcuts ----
scrape-inspect:
	pursue scrape inspect --out data/inspect/

scrape:
	pursue scrape run --pages all --out data/manifests/release_01.json

download:
	pursue download run --manifest data/manifests/release_01.json

ocr:
	pursue ocr run --manifest data/manifests/release_01.json

ingest:
	pursue index ingest --manifest data/manifests/release_01.json

serve:
	pursue serve

# ---- dev quality ----
test:
	pytest

lint:
	ruff check src tests

typecheck:
	mypy src

fmt:
	ruff format src tests
	ruff check --fix src tests

# ---- infra ----
db-up:
	docker compose up -d postgres

db-down:
	docker compose down

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
