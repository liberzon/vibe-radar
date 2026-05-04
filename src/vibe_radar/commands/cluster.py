from __future__ import annotations
import os
import asyncpg
import structlog

from analysis.cluster import (
    fetch_corpus, _doc_to_text, cluster_texts, top_terms_per_cluster,
    write_themes, score_themes, label_themes_with_llm,
)

log = structlog.get_logger(__name__)


async def run(*, days: int, min_cluster_size: int, max_clusters: int,
              label: bool = True, label_model: str = "haiku") -> None:
    dsn = os.environ.get("DATABASE_URL", "postgresql://reddit:reddit@localhost:5432/reddit")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    try:
        docs = await fetch_corpus(pool, days=days)
        if len(docs) < max(20, min_cluster_size * 4):
            log.warning("cluster.too_few_docs", n=len(docs))
            return
        log.info("cluster.fetched", n=len(docs), days=days)

        texts = [_doc_to_text(d) for d in docs]
        vec, km, X, labels = cluster_texts(texts, k_min=4, k_max=max_clusters)
        terms = top_terms_per_cluster(vec, km, top_n=8)
        n_themes = await write_themes(pool, docs=docs, labels=labels, top_terms=terms, replace=True)
        log.info("cluster.themes_written", n=n_themes)

        scored = await score_themes(pool)
        log.info("cluster.scored", n=scored)

        if label:
            labeled = await label_themes_with_llm(pool, model=label_model)
            log.info("cluster.labeled", n=labeled)
    finally:
        await pool.close()
