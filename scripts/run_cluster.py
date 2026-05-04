"""Cluster recent documents into themes, score them, and label them via Claude.

Usage:
    python -m scripts.run_cluster                        # 30-day window
    python -m scripts.run_cluster --days 7
    python -m scripts.run_cluster --no-label             # skip the LLM labeling pass
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
import sys
import asyncpg
import structlog

from analysis.cluster import (
    fetch_corpus, _doc_to_text, cluster_texts, top_terms_per_cluster,
    write_themes, score_themes, label_themes_with_llm,
)

log = structlog.get_logger(__name__)


def configure_logging() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(message)s", stream=sys.stdout)
    structlog.configure(processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ])


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--min-cluster-size", type=int, default=5)
    p.add_argument("--max-clusters", type=int, default=40)
    p.add_argument("--no-label", action="store_true", help="skip LLM theme labeling pass")
    p.add_argument("--label-model", default="haiku")
    args = p.parse_args()

    configure_logging()
    dsn = os.environ.get("DATABASE_URL", "postgresql://reddit:reddit@localhost:5432/reddit")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    try:
        docs = await fetch_corpus(pool, days=args.days)
        if len(docs) < max(20, args.min_cluster_size * 4):
            log.warning("cluster.too_few_docs", n=len(docs))
            return
        log.info("cluster.fetched", n=len(docs), days=args.days)

        texts = [_doc_to_text(d) for d in docs]
        vec, km, X, labels = cluster_texts(texts, k_min=4, k_max=args.max_clusters)
        terms = top_terms_per_cluster(vec, km, top_n=8)
        n_themes = await write_themes(pool, docs=docs, labels=labels, top_terms=terms, replace=True)
        log.info("cluster.themes_written", n=n_themes)

        scored = await score_themes(pool)
        log.info("cluster.scored", n=scored)

        if not args.no_label:
            labeled = await label_themes_with_llm(pool, model=args.label_model)
            log.info("cluster.labeled", n=labeled)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
