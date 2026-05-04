from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
import structlog

from .client import RedditClient
from .config import Source
from .normalize import flatten_comment_tree, normalize_post
from .storage import Storage

log = structlog.get_logger(__name__)


async def fetch_listing_page(
    client: RedditClient, source: Source, after: str | None, limit: int = 100,
) -> dict[str, Any]:
    if source.kind == "subreddit":
        path = f"/r/{source.name}/{source.listing}"
        params = {"limit": limit}
    elif source.kind == "search":
        path = "/search"
        params = {"q": source.query, "sort": source.sort, "t": source.timeframe, "limit": limit}
    elif source.kind == "user":
        path = f"/user/{source.name}/submitted"
        params = {"limit": limit}
    else:
        raise ValueError(f"unknown kind: {source.kind}")
    if after:
        params["after"] = after
    return await client.get(path, params=params)


async def ingest_listing(client: RedditClient, storage: Storage, source: Source) -> dict[str, int]:
    """Walk a listing forward from newest until we hit the previous high-water mark."""
    hwm = await storage.get_high_water_mark(source.key)
    after: str | None = None
    total_seen = 0
    total_stored = 0
    newest_ts: datetime | None = None
    newest_fullname: str | None = None
    pages = 0

    while total_seen < source.max_items_per_tick:
        page = await fetch_listing_page(client, source, after=after)
        pages += 1
        children = (page.get("data") or {}).get("children", [])
        if not children:
            break

        post_rows: list[dict[str, Any]] = []
        for ch in children:
            if ch.get("kind") != "t3":
                continue
            row = normalize_post(ch.get("data") or {})
            total_seen += 1
            if newest_ts is None and row["created_utc"]:
                newest_ts = row["created_utc"]
                newest_fullname = row["id"]
            if hwm and row["created_utc"] and row["created_utc"] <= hwm:
                # We've reached previously-seen territory.
                continue
            post_rows.append(row)

            # Subreddit + author breadcrumbs
            if row["author_id"]:
                await storage.upsert_author(id=row["author_id"], username=row["author_username"])

        # Best-effort subreddit stub (full metadata fetched lazily)
        for sub in {r["subreddit"] for r in post_rows if r["subreddit"]}:
            await storage.upsert_subreddit(sub)

        total_stored += await storage.upsert_posts(post_rows)

        # Stop if the page already crossed HWM (no more new content older than what we just stored).
        crossed = hwm is not None and any(
            (r["created_utc"] and r["created_utc"] <= hwm)
            for r in (normalize_post(c.get("data") or {}) for c in children if c.get("kind") == "t3")
        )
        if crossed:
            break

        after = (page.get("data") or {}).get("after")
        if not after:
            break

    if newest_ts:
        await storage.set_high_water_mark(source.key, newest_ts, newest_fullname)

    log.info(
        "ingest.listing.done",
        source=source.key, pages=pages, seen=total_seen, stored=total_stored,
        hwm=hwm.isoformat() if hwm else None,
        new_hwm=newest_ts.isoformat() if newest_ts else None,
    )
    return {"seen": total_seen, "stored": total_stored, "pages": pages}


async def ingest_post_comments(
    client: RedditClient, storage: Storage, post_fullname: str, depth: int = 5,
) -> int:
    """Fetch and store the comment forest for a single post."""
    # /comments/{id} expects the bare id (no t3_ prefix)
    bare = post_fullname.removeprefix("t3_")
    path = f"/comments/{bare}"
    page = await client.get(path, params={"depth": depth, "limit": 500, "showmore": False})
    if not isinstance(page, list):
        return 0
    rows = flatten_comment_tree(page)
    # Ensure post_id is set; Reddit returns link_id on each comment.
    for r in rows:
        if not r["post_id"]:
            r["post_id"] = post_fullname
    # Persist authors first (FK-safe)
    seen_authors: set[tuple[str, str | None]] = set()
    for r in rows:
        if r["author_id"]:
            seen_authors.add((r["author_id"], r["author_username"]))
    for aid, uname in seen_authors:
        await storage.upsert_author(id=aid, username=uname)
    return await storage.upsert_comments(rows)
