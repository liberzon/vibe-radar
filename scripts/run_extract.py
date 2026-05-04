"""Pull unprocessed documents, run extraction via the Claude Code CLI, persist results.

Usage:
    python -m scripts.run_extract --limit 50 --model haiku --concurrency 2
    python -m scripts.run_extract --since "2025-01-01" --source reddit

This is idempotent: documents already in `extraction_runs` for the current
prompt_version are skipped. Bump PROMPT_VERSION in claude_cli.py to force re-run.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import logging
import os
import sys
import asyncpg
import structlog

from analysis.claude_cli import run_extraction, CLIResult, EXTRACTION_SYSTEM_PROMPT

PROMPT_VERSION = "extract-v1"
EXTRACTOR = "claude-cli"

log = structlog.get_logger(__name__)


SELECT_PENDING = """
SELECT d.id::text, d.source, d.kind, d.title, d.body, d.url
FROM documents d
LEFT JOIN extraction_runs r
    ON r.document_id = d.id
   AND r.prompt_version = $1
   AND r.extractor = $2
WHERE r.id IS NULL
  AND COALESCE(d.body, '') <> ''
  AND ($3::text IS NULL OR d.source = $3)
  AND ($4::timestamptz IS NULL OR d.created_utc >= $4)
ORDER BY d.created_utc DESC
LIMIT $5
"""


def configure_logging() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(message)s", stream=sys.stdout)
    structlog.configure(processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ])


def doc_to_text(row: asyncpg.Record) -> str:
    parts = []
    if row["kind"]:
        parts.append(f"[{row['source']}:{row['kind']}]")
    if row["title"]:
        parts.append(f"Title: {row['title']}")
    if row["url"]:
        parts.append(f"URL: {row['url']}")
    if row["body"]:
        parts.append(row["body"])
    return "\n".join(parts)


async def persist_extraction(
    pool: asyncpg.Pool, *, document_id: str, model: str, result: CLIResult,
) -> None:
    so = result.structured_output or {}
    async with pool.acquire() as c:
        async with c.transaction():
            await c.execute(
                """
                INSERT INTO extraction_runs
                    (document_id, prompt_version, extractor, model, status,
                     cost_usd, duration_ms, raw)
                VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (document_id, prompt_version, extractor) DO UPDATE SET
                    status = EXCLUDED.status,
                    cost_usd = EXCLUDED.cost_usd,
                    duration_ms = EXCLUDED.duration_ms,
                    raw = EXCLUDED.raw,
                    extracted_at = now()
                """,
                document_id, PROMPT_VERSION, EXTRACTOR, model,
                "ok" if result.structured_output and not result.is_error else "failed",
                result.cost_usd, result.duration_ms, json.dumps(so),
            )

            for p in so.get("products") or []:
                name = (p.get("name") or "").strip()
                if not name:
                    continue
                # Upsert canonical product
                product_id = await c.fetchval(
                    """
                    INSERT INTO products (canonical_name, homepage, first_mentioned_at,
                                          last_mentioned_at, mention_count)
                    VALUES (lower($1), $2, now(), now(), 1)
                    ON CONFLICT (canonical_name) DO UPDATE SET
                        homepage = COALESCE(products.homepage, EXCLUDED.homepage),
                        last_mentioned_at = now(),
                        mention_count = products.mention_count + 1
                    RETURNING id
                    """,
                    name, p.get("homepage"),
                )
                await c.execute(
                    """
                    INSERT INTO mentions
                        (document_id, product_id, mention_kind, surface_text,
                         normalized_name, confidence, extracted_via)
                    VALUES ($1::uuid, $2, 'product', $3, $4, $5, 'llm')
                    ON CONFLICT DO NOTHING
                    """,
                    document_id, product_id, name, name.lower(),
                    0.8 if p.get("evidence_quote") else 0.6,
                )

            for r in so.get("revenue_claims") or []:
                metric = r.get("metric") or "other"
                amount = r.get("amount_usd")
                if amount is None:
                    continue
                await c.execute(
                    """
                    INSERT INTO revenue_claims
                        (document_id, claim_text, metric, amount, currency,
                         claim_type, confidence)
                    VALUES ($1::uuid, $2, $3, $4, 'USD', $5, $6)
                    """,
                    document_id, r.get("evidence_quote") or "",
                    metric, amount, r.get("claim_type") or "self-reported",
                    0.8,
                )


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--source", default=None, help="filter: 'reddit'|'hn'|...")
    p.add_argument("--since", default=None, help="ISO date filter on created_utc")
    p.add_argument("--model", default="haiku")
    p.add_argument("--concurrency", type=int, default=2)
    args = p.parse_args()

    configure_logging()
    dsn = os.environ.get("DATABASE_URL", "postgresql://reddit:reddit@localhost:5432/reddit")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)

    try:
        async with pool.acquire() as c:
            rows = await c.fetch(
                SELECT_PENDING, PROMPT_VERSION, EXTRACTOR, args.source, args.since, args.limit,
            )
        if not rows:
            log.info("extract.nothing_pending")
            return

        log.info("extract.pending", n=len(rows), model=args.model, concurrency=args.concurrency)
        sem = asyncio.Semaphore(args.concurrency)
        ok = err = 0
        total_cost = 0.0

        async def process(row: asyncpg.Record) -> None:
            nonlocal ok, err, total_cost
            async with sem:
                doc_id = row["id"]
                text = doc_to_text(row)
                try:
                    res = await run_extraction(text, model=args.model)
                except Exception as exc:  # noqa: BLE001
                    err += 1
                    log.warning("extract.failed", document_id=doc_id, error=str(exc))
                    return
                if res.is_error or res.structured_output is None:
                    err += 1
                    log.warning("extract.empty", document_id=doc_id)
                    return
                await persist_extraction(pool, document_id=doc_id, model=args.model, result=res)
                ok += 1
                total_cost += res.cost_usd
                log.info("extract.done",
                         document_id=doc_id, cost=res.cost_usd, ms=res.duration_ms,
                         products=len(res.structured_output.get("products") or []),
                         revenue=len(res.structured_output.get("revenue_claims") or []))

        await asyncio.gather(*(process(r) for r in rows))
        log.info("extract.summary", ok=ok, err=err, total_cost_usd=round(total_cost, 4))
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
