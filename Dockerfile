# Collector image. NOT for the LLM extractor — that runs on the host where the
# `claude` CLI is OAuth-authenticated to your Claude Code subscription.
#
# Build:  docker build -t reddit-collector .
# Run:    docker run --rm --env-file .env --network host reddit-collector \
#             python -m scripts.run_all

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
RUN pip install \
        "httpx>=0.27" \
        "asyncpg>=0.29" \
        "pydantic>=2.6" \
        "pydantic-settings>=2.2" \
        "pyyaml>=6.0" \
        "tenacity>=8.2" \
        "structlog>=24.1" \
        "praw>=7.7"

COPY src/ ./src/
COPY scripts/ ./scripts/
COPY config/ ./config/

ENV PYTHONPATH=/app/src

# Default command runs one collection tick.
CMD ["python", "-m", "scripts.run_all"]
