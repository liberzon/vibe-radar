from __future__ import annotations
import json
from datetime import datetime
from typing import Any, Iterable
import asyncpg
import structlog

log = structlog.get_logger(__name__)


class Storage:
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=8)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def upsert_subreddit(self, name: str, meta: dict[str, Any] | None = None) -> None:
        meta = meta or {}
        async with self._pool.acquire() as c:  # type: ignore[union-attr]
            await c.execute(
                """
                INSERT INTO subreddits (name, display_name, title, public_description,
                                        subscribers, over18, created_utc, last_synced_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7, now())
                ON CONFLICT (name) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    title = EXCLUDED.title,
                    public_description = EXCLUDED.public_description,
                    subscribers = EXCLUDED.subscribers,
                    over18 = EXCLUDED.over18,
                    last_synced_at = now()
                """,
                name.lower(),
                meta.get("display_name"),
                meta.get("title"),
                meta.get("public_description"),
                meta.get("subscribers"),
                meta.get("over18"),
                meta.get("created_utc"),
            )

    async def upsert_author(self, *, id: str, username: str | None) -> None:
        if not id:
            return
        async with self._pool.acquire() as c:  # type: ignore[union-attr]
            await c.execute(
                """
                INSERT INTO authors (id, username, last_seen_at)
                VALUES ($1,$2, now())
                ON CONFLICT (id) DO UPDATE SET
                    username = COALESCE(EXCLUDED.username, authors.username),
                    last_seen_at = now()
                """,
                id, username,
            )

    async def upsert_posts(self, rows: Iterable[dict[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = """
        INSERT INTO posts (id, subreddit, author_id, author_username,
            title, selftext, url, permalink, domain, is_self, over18, spoiler,
            stickied, locked, removed, score, upvote_ratio, num_comments,
            created_utc, edited_utc, deleted_at, content_hash, last_seen_at, last_refreshed_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,
                $19,$20,$21,$22, now(), now())
        ON CONFLICT (id) DO UPDATE SET
            title = EXCLUDED.title,
            selftext = EXCLUDED.selftext,
            url = EXCLUDED.url,
            permalink = EXCLUDED.permalink,
            score = EXCLUDED.score,
            upvote_ratio = EXCLUDED.upvote_ratio,
            num_comments = EXCLUDED.num_comments,
            edited_utc = EXCLUDED.edited_utc,
            deleted_at = COALESCE(EXCLUDED.deleted_at, posts.deleted_at),
            removed = EXCLUDED.removed,
            content_hash = EXCLUDED.content_hash,
            last_seen_at = now(),
            last_refreshed_at = now()
        """
        async with self._pool.acquire() as c:  # type: ignore[union-attr]
            await c.executemany(sql, [(
                r["id"], r["subreddit"], r["author_id"], r["author_username"],
                r["title"], r["selftext"], r["url"], r["permalink"], r["domain"],
                r["is_self"], r["over18"], r["spoiler"], r["stickied"], r["locked"],
                r["removed"], r["score"], r["upvote_ratio"], r["num_comments"],
                r["created_utc"], r["edited_utc"], r["deleted_at"], r["content_hash"],
            ) for r in rows])
        return len(rows)

    async def upsert_comments(self, rows: Iterable[dict[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = """
        INSERT INTO comments (id, post_id, parent_id, subreddit, author_id, author_username,
            body, score, depth, removed, created_utc, edited_utc, deleted_at,
            content_hash, last_seen_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14, now())
        ON CONFLICT (id) DO UPDATE SET
            body = EXCLUDED.body,
            score = EXCLUDED.score,
            edited_utc = EXCLUDED.edited_utc,
            deleted_at = COALESCE(EXCLUDED.deleted_at, comments.deleted_at),
            removed = EXCLUDED.removed,
            content_hash = EXCLUDED.content_hash,
            last_seen_at = now()
        """
        async with self._pool.acquire() as c:  # type: ignore[union-attr]
            await c.executemany(sql, [(
                r["id"], r["post_id"], r["parent_id"], r["subreddit"], r["author_id"],
                r["author_username"], r["body"], r["score"], r["depth"], r["removed"],
                r["created_utc"], r["edited_utc"], r["deleted_at"], r["content_hash"],
            ) for r in rows])
        return len(rows)

    async def archive_payload(self, *, endpoint: str, params_hash: str, status: int,
                              payload: dict[str, Any] | None, payload_uri: str | None) -> None:
        async with self._pool.acquire() as c:  # type: ignore[union-attr]
            await c.execute(
                """
                INSERT INTO raw_payloads (endpoint, params_hash, status_code, payload, payload_uri)
                VALUES ($1,$2,$3,$4,$5)
                """,
                endpoint, params_hash, status,
                json.dumps(payload) if payload is not None else None,
                payload_uri,
            )

    async def get_high_water_mark(self, source_key: str) -> datetime | None:
        async with self._pool.acquire() as c:  # type: ignore[union-attr]
            return await c.fetchval(
                "SELECT high_water_mark FROM source_state WHERE source_key = $1",
                source_key,
            )

    async def set_high_water_mark(self, source_key: str, hwm: datetime, last_fullname: str | None) -> None:
        async with self._pool.acquire() as c:  # type: ignore[union-attr]
            await c.execute(
                """
                INSERT INTO source_state (source_key, high_water_mark, last_fullname, last_run_at, last_status)
                VALUES ($1,$2,$3, now(), 'ok')
                ON CONFLICT (source_key) DO UPDATE SET
                    high_water_mark = GREATEST(source_state.high_water_mark, EXCLUDED.high_water_mark),
                    last_fullname = EXCLUDED.last_fullname,
                    last_run_at = now(),
                    last_status = 'ok'
                """,
                source_key, hwm, last_fullname,
            )
