.PHONY: install db migrate run run-reddit run-hn extract cluster status test clean docker-collect

PY := PYTHONPATH=src python3

install:
	pip install -e ".[cluster,praw]"

db:
	docker compose up -d postgres
	@echo "waiting for postgres..."
	@until docker compose exec -T postgres pg_isready -U reddit >/dev/null 2>&1; do sleep 1; done
	@echo "postgres ready."

migrate:
	docker compose exec -T postgres psql -U reddit -d reddit -f /docker-entrypoint-initdb.d/001_init.sql || true
	docker compose exec -T postgres psql -U reddit -d reddit -f /docker-entrypoint-initdb.d/002_multisource.sql || true
	docker compose exec -T postgres psql -U reddit -d reddit -f /docker-entrypoint-initdb.d/003_extraction_state.sql || true

run:
	$(PY) -m scripts.run_all

run-reddit:
	$(PY) -m scripts.run_all --reddit-only

run-hn:
	$(PY) -m scripts.run_all --hn-only

extract:
	$(PY) -m scripts.run_extract --limit 50 --model haiku --concurrency 2

cluster:
	$(PY) -m scripts.run_cluster --days 30

status:
	$(PY) -m scripts.run_status

# Optional: run the collector inside a container (e.g. for cloud deploy).
# Extraction stays on the host — see Dockerfile note.
docker-collect:
	docker compose --profile collect up --build collector

test:
	$(PY) -m pytest tests/ -q --ignore=tests/test_claude_cli.py

clean:
	docker compose down -v
