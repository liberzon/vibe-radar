from __future__ import annotations
import html
from datetime import datetime, timezone
from typing import Any
import asyncpg
import structlog

from .client import HNClient
from common.documents import upsert_document


def _clean(s: str | None) -> str | None:
    """Algolia returns HTML-entity-encoded text; strip the encoding so downstream
    text analysis (TF-IDF, embeddings, LLM extraction) doesn't see `x2f`/`x27`."""
    return html.unescape(s) if s else s

log = structlog.get_logger(__name__)


def _ts(epoch: int | float | None) -> datetime | None:
    return datetime.fromtimestamp(epoch, tz=timezone.utc) if epoch else None


async def ingest_search(
    client: HNClient,
    pool: asyncpg.Pool,
    *,
    query: str,
    tags: str = "story",
    max_pages: int = 5,
) -> int:
    """Ingest stories matching `query`. Use tags='story,(launch_hn,show_hn)'
    to focus on launches when prospecting for product mentions."""
    total = 0
    for page in range(max_pages):
        body = await client.search(query, tags=tags, page=page)
        hits = body.get("hits") or []
        if not hits:
            break
        for h in hits:
            sid = str(h.get("objectID"))
            created = _ts(h.get("created_at_i")) or datetime.now(tz=timezone.utc)
            await upsert_document(
                pool,
                source="hn",
                source_id=sid,
                kind="story" if "story" in (h.get("_tags") or []) else "comment",
                title=_clean(h.get("title")),
                body=_clean(h.get("story_text") or h.get("comment_text")),
                url=h.get("url") or f"https://news.ycombinator.com/item?id={sid}",
                author_handle=h.get("author"),
                score=h.get("points"),
                created_utc=created,
            )
            total += 1
    log.info("hn.ingest.search", query=query, ingested=total)
    return total


async def ingest_item_tree(client: HNClient, pool: asyncpg.Pool, item_id: int) -> int:
    """Recursively ingest an HN item and its comment tree (bounded by API)."""
    stack = [item_id]
    visited: set[int] = set()
    n = 0
    while stack:
        iid = stack.pop()
        if iid in visited:
            continue
        visited.add(iid)
        item = await client.item(iid)
        if not item or item.get("deleted") or item.get("dead"):
            continue
        kind = item.get("type") or "story"
        await upsert_document(
            pool,
            source="hn",
            source_id=str(iid),
            kind=kind,
            parent_source_id=str(item.get("parent")) if item.get("parent") else None,
            title=_clean(item.get("title")),
            body=_clean(item.get("text")),
            url=item.get("url") or f"https://news.ycombinator.com/item?id={iid}",
            author_handle=item.get("by"),
            score=item.get("score"),
            created_utc=_ts(item.get("time")) or datetime.now(tz=timezone.utc),
        )
        n += 1
        for kid in item.get("kids") or []:
            stack.append(int(kid))
    return n
