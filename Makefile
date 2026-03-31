.PHONY: help dev test lint fmt clean build deploy

help:
	@echo "Available commands:"
	@echo "  make dev       - Start development environment"
	@echo "  make test      - Run test suite"
	@echo "  make lint      - Run linters"
	@echo "  make fmt       - Format code"
	@echo "  make build     - Build Docker images"
	@echo "  make clean     - Clean up containers and volumes"
	@echo "  make ingest    - Run ingestion CLI"
	@echo "  make probe     - Run probe CLI"

dev:
	docker compose up -d
	@echo "Services started:"
	@echo "  Web UI: http://localhost:5173"
	@echo "  API: http://localhost:8000"
	@echo "  API Docs: http://localhost:8000/docs"

test:
	uv run pytest tests/ -v --cov=app --cov=worker --cov-report=term-missing

lint:
	uv run ruff check app/ worker/ cli/ tests/
	cd web && bun run lint

fmt:
	uv run ruff format app/ worker/ cli/ tests/
	cd web && bun run format

build:
	docker compose build

clean:
	docker compose down -v
	rm -rf data/*.db
	rm -rf __pycache__ .pytest_cache .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

ingest:
	@if [ -z "$(file)" ]; then \
		echo "Usage: make ingest file=path/to/data.json"; \
		exit 1; \
	fi
	uv run python cli/ingest_json.py $(file) --auto-detect

probe:
	@if [ -z "$(filter)" ]; then \
		echo "Usage: make probe filter='model:llama'"; \
		echo "Options: --all, --status=online, --model=llama, --gpu"; \
		exit 1; \
	fi
	uv run python cli/rescan_hosts.py $(filter)

install:
	uv sync --dev
	cd web && bun install

refresh-excludes:
	uv run python cli/refresh_dynamic_excludes.py --output app/excludes.generated.conf

migrate:
	alembic upgrade head

seed:
	@echo "Seeding sample data..."
	uv run python scripts/seed_sample.py

logs:
	docker compose logs -f

stop:
	docker compose stop

restart:
	docker compose restart

status:
	docker compose ps

db-shell:
	sqlite3 data/ollama.db

redis-cli:
	docker compose exec redis redis-cli

worker-logs:
	docker compose logs -f worker

api-logs:
	docker compose logs -f api

web-logs:
	docker compose logs -f web
