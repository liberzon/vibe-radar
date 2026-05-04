"""Shared `documents` upsert used by every source collector."""
from __future__ import annotations
from datetime import datetime
from typing import Any
import asyncpg


async def upsert_document(
    pool: asyncpg.Pool,
    *,
    source: str,
    source_id: str,
    kind: str,
    title: str | None,
    body: str | None,
    url: str | None,
    author_handle: str | None,
    score: int | None,
    created_utc: datetime,
    parent_source_id: str | None = None,
    language: str | None = None,
    raw_ref: str | None = None,
) -> str:
    """Insert/update a row in `documents`. Returns the document's UUID."""
    sql = """
    INSERT INTO documents (source, source_id, kind, parent_source_id, author_handle,
        title, body, url, language, score, created_utc, raw_ref)
    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
    ON CONFLICT (source, source_id) DO UPDATE SET
        title = EXCLUDED.title,
        body = EXCLUDED.body,
        url = EXCLUDED.url,
        score = EXCLUDED.score,
        author_handle = EXCLUDED.author_handle,
        language = COALESCE(EXCLUDED.language, documents.language),
        fetched_at = now()
    RETURNING id::text
    """
    async with pool.acquire() as c:
        return await c.fetchval(
            sql, source, source_id, kind, parent_source_id, author_handle,
            title, body, url, language, score, created_utc, raw_ref,
        )
