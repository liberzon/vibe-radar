"""One-shot ingestion of a subreddit listing (and optionally its comments).

Usage:
    python -m scripts.run_subreddit --subreddit <name> --listing new
    python -m scripts.run_subreddit --subreddit <name> --with-comments
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import sys
import structlog

from reddit_collector.config import Settings, Source
from reddit_collector.client import RedditClient
from reddit_collector.oauth import RedditAuth
from reddit_collector.storage import Storage
from reddit_collector.ingestion import ingest_listing, ingest_post_comments


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(message)s", stream=sys.stdout)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
    )


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--subreddit", required=True)
    p.add_argument("--listing", default="new", choices=["new", "hot", "top", "rising"])
    p.add_argument("--with-comments", action="store_true")
    p.add_argument("--max-items", type=int, default=200)
    p.add_argument("--comment-depth", type=int, default=5)
    args = p.parse_args()

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(settings.log_level)

    source = Source(
        kind="subreddit",
        name=args.subreddit,
        listing=args.listing,
        max_items_per_tick=args.max_items,
        fetch_comments=args.with_comments,
        comment_depth=args.comment_depth,
    )

    auth = RedditAuth(
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        user_agent=settings.reddit_user_agent,
        username=settings.reddit_username,
        password=settings.reddit_password,
    )
    storage = Storage(settings.database_url)
    await storage.connect()
    try:
        async with RedditClient(auth, settings.reddit_user_agent) as client:
            stats = await ingest_listing(client, storage, source)
            print(f"listing: {stats}")

            if args.with_comments:
                # Refetch the most recent posts we have for this sub and pull comments.
                async with storage._pool.acquire() as conn:  # type: ignore[union-attr]
                    rows = await conn.fetch(
                        """
                        SELECT id FROM posts
                        WHERE subreddit = $1
                        ORDER BY created_utc DESC
                        LIMIT $2
                        """,
                        args.subreddit.lower(), min(args.max_items, 50),
                    )
                for row in rows:
                    n = await ingest_post_comments(client, storage, row["id"], depth=args.comment_depth)
                    print(f"comments: post={row['id']} stored={n}")
    finally:
        await storage.close()


if __name__ == "__main__":
    asyncio.run(main())
