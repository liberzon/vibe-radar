"""Run one tick of every source defined in config/sources.yaml.

Iterates Reddit sources sequentially (one OAuth client → shared rate limiter),
then the HN sources. Designed to be run by cron / k8s CronJob every N minutes;
each source's own poll_interval is advisory — short-interval sources will
have shorter HWM gaps between visits when you cron at a tight cadence.

Usage:
    python -m scripts.run_all
    python -m scripts.run_all --config config/sources.yaml --reddit-only
    python -m scripts.run_all --hn-only
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
import sys
import asyncpg
import structlog

from reddit_collector.config import Settings, load_sources_file
from reddit_collector.client import RedditClient
from reddit_collector.oauth import RedditAuth
from reddit_collector.storage import Storage
from reddit_collector.ingestion import ingest_listing

from hn_collector.client import HNClient
from hn_collector.ingest import ingest_search

log = structlog.get_logger(__name__)


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(message)s", stream=sys.stdout)
    structlog.configure(processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ])


async def run_reddit(settings: Settings, sources, storage: Storage) -> dict:
    auth = RedditAuth(
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        user_agent=settings.reddit_user_agent,
        username=settings.reddit_username,
        password=settings.reddit_password,
    )
    totals = {"sources": 0, "stored": 0, "failed": 0}
    async with RedditClient(auth, settings.reddit_user_agent) as client:
        for src in sources:
            try:
                stats = await ingest_listing(client, storage, src)
                totals["sources"] += 1
                totals["stored"] += stats["stored"]
                log.info("run_all.reddit.ok", source=src.key, **stats)
            except Exception as exc:  # noqa: BLE001
                totals["failed"] += 1
                log.warning("run_all.reddit.fail", source=src.key, error=str(exc))
    return totals


async def run_hn(ua: str, hn_sources, pool: asyncpg.Pool) -> dict:
    totals = {"sources": 0, "stored": 0, "failed": 0}
    async with HNClient(user_agent=ua) as client:
        for src in hn_sources:
            try:
                n = await ingest_search(client, pool, query=src.query, tags=src.tags, max_pages=src.pages)
                totals["sources"] += 1
                totals["stored"] += n
                log.info("run_all.hn.ok", query=src.query, tags=src.tags, ingested=n)
            except Exception as exc:  # noqa: BLE001
                totals["failed"] += 1
                log.warning("run_all.hn.fail", query=src.query, error=str(exc))
    return totals


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config/sources.yaml")
    p.add_argument("--reddit-only", action="store_true")
    p.add_argument("--hn-only", action="store_true")
    args = p.parse_args()

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(settings.log_level)
    cfg = load_sources_file(args.config)

    storage = Storage(settings.database_url)
    await storage.connect()
    pool = storage._pool  # reuse pool for HN inserts
    try:
        if not args.hn_only:
            r = await run_reddit(settings, cfg.sources, storage)
            log.info("run_all.reddit.summary", **r)
        if not args.reddit_only:
            h = await run_hn(settings.reddit_user_agent, cfg.hn_sources, pool)
            log.info("run_all.hn.summary", **h)
    finally:
        await storage.close()


if __name__ == "__main__":
    asyncio.run(main())
