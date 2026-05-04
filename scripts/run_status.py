"""Quick volume + health summary."""
from __future__ import annotations
import asyncio
import os
import asyncpg


async def main() -> None:
    dsn = os.environ.get("DATABASE_URL", "postgresql://reddit:reddit@localhost:5432/reddit")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        async with pool.acquire() as c:
            counts = await c.fetchrow("""
                SELECT
                    (SELECT COUNT(*) FROM documents)                                AS docs_total,
                    (SELECT COUNT(*) FROM documents WHERE source = 'reddit')        AS docs_reddit,
                    (SELECT COUNT(*) FROM documents WHERE source = 'hn')            AS docs_hn,
                    (SELECT COUNT(*) FROM documents
                       WHERE created_utc >= now() - interval '24 hours')             AS docs_24h,
                    (SELECT COUNT(*) FROM posts)                                    AS posts,
                    (SELECT COUNT(*) FROM comments)                                 AS comments,
                    (SELECT COUNT(*) FROM products)                                 AS products,
                    (SELECT COUNT(*) FROM revenue_claims)                           AS revenue_claims,
                    (SELECT COUNT(*) FROM themes)                                   AS themes,
                    (SELECT COUNT(*) FROM extraction_runs WHERE status = 'ok')      AS extractions_ok
            """)
            top_subs = await c.fetch("""
                SELECT subreddit, COUNT(*) AS n FROM posts
                WHERE created_utc >= now() - interval '7 days'
                GROUP BY subreddit ORDER BY n DESC LIMIT 5
            """)
            top_themes = await c.fetch("""
                SELECT label, document_count, distinct_authors, score
                FROM themes ORDER BY score DESC NULLS LAST LIMIT 5
            """)

        print("─── volume ───")
        for k, v in counts.items():
            print(f"  {k:18s} {v}")
        print("─── top subreddits (7d) ───")
        for r in top_subs:
            print(f"  {r['subreddit']:30s} {r['n']}")
        print("─── top themes by score ───")
        for r in top_themes:
            print(f"  [{r['score'] or 0:5.2f}] {r['label']}  (docs={r['document_count']}, authors={r['distinct_authors']})")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
