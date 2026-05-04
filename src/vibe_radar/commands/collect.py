from __future__ import annotations
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
                log.info("collect.reddit.ok", source=src.key, **stats)
            except Exception as exc:  # noqa: BLE001
                totals["failed"] += 1
                log.warning("collect.reddit.fail", source=src.key, error=str(exc))
    return totals


async def run_hn(ua: str, hn_sources, pool: asyncpg.Pool) -> dict:
    totals = {"sources": 0, "stored": 0, "failed": 0}
    async with HNClient(user_agent=ua) as client:
        for src in hn_sources:
            try:
                n = await ingest_search(client, pool, query=src.query, tags=src.tags, max_pages=src.pages)
                totals["sources"] += 1
                totals["stored"] += n
                log.info("collect.hn.ok", query=src.query, tags=src.tags, ingested=n)
            except Exception as exc:  # noqa: BLE001
                totals["failed"] += 1
                log.warning("collect.hn.fail", query=src.query, error=str(exc))
    return totals


async def run(*, config_path: str, reddit_only: bool = False, hn_only: bool = False) -> None:
    settings = Settings()  # type: ignore[call-arg]
    cfg = load_sources_file(config_path)

    storage = Storage(settings.database_url)
    await storage.connect()
    try:
        if not hn_only:
            r = await run_reddit(settings, cfg.sources, storage)
            log.info("collect.reddit.summary", **r)
        if not reddit_only:
            h = await run_hn(settings.reddit_user_agent, cfg.hn_sources, storage._pool)
            log.info("collect.hn.summary", **h)
    finally:
        await storage.close()
