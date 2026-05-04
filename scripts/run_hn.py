"""Ingest Hacker News stories matching a query into `documents`.

Usage:
    python -m scripts.run_hn --query "<your-query>" --tags "story,(show_hn,launch_hn)"
    python -m scripts.run_hn --query "<your-query>" --pages 3
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
import sys
import asyncpg
import structlog

from hn_collector.client import HNClient
from hn_collector.ingest import ingest_search


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=level, format="%(message)s", stream=sys.stdout)
    structlog.configure(processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ])


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--query", required=True)
    p.add_argument("--tags", default="story")
    p.add_argument("--pages", type=int, default=3)
    args = p.parse_args()

    configure_logging()
    dsn = os.environ.get("DATABASE_URL", "postgresql://reddit:reddit@localhost:5432/reddit")
    ua = os.environ.get("REDDIT_USER_AGENT", "reddit-collector/0.1 (HN ingest)")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    try:
        async with HNClient(user_agent=ua) as client:
            n = await ingest_search(client, pool, query=args.query, tags=args.tags, max_pages=args.pages)
            print(f"hn ingested: {n}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
