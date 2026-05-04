"""Cluster documents into themes.

v1: TF-IDF + MiniBatchKMeans with k chosen by silhouette score on a sample.
- No torch, no API. ~10s for ~10k docs on a laptop.
- Output rows in `themes` and `theme_documents`.
- Optional: label each theme via the Claude Code CLI (one short call per theme).

When we want better quality (or RAG), swap `_vectorize` for sentence-transformers
embeddings and add a pgvector column. The rest of the pipeline doesn't change.
"""
from __future__ import annotations
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Sequence
import asyncpg
import structlog

log = structlog.get_logger(__name__)


@dataclass
class ClusteredDoc:
    document_id: str
    cluster_id: int
    distance_to_centroid: float


@dataclass
class ClusterSummary:
    cluster_id: int
    size: int
    distinct_authors: int
    last_seen_at: datetime
    top_terms: list[str]
    sample_doc_ids: list[str]


def _vectorize(texts: Sequence[str]):
    """TF-IDF vectorizer optimized for short-form social text."""
    from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: PLC0415
    vec = TfidfVectorizer(
        max_features=20_000,
        ngram_range=(1, 2),
        min_df=2,
        max_df=0.85,
        sublinear_tf=True,
        strip_accents="unicode",
        lowercase=True,
        stop_words="english",
    )
    X = vec.fit_transform(texts)
    return vec, X


def _pick_k(X, *, k_min: int = 4, k_max: int = 40, sample_size: int = 2000) -> int:
    """Pick k by silhouette on a sample. Cheap, good enough for our purposes."""
    from sklearn.cluster import MiniBatchKMeans  # noqa: PLC0415
    from sklearn.metrics import silhouette_score  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    n = X.shape[0]
    if n < k_min * 5:
        return max(2, n // 5)

    rng = np.random.default_rng(42)
    if n > sample_size:
        idx = rng.choice(n, size=sample_size, replace=False)
        Xs = X[idx]
    else:
        Xs = X

    best_k, best_score = k_min, -1.0
    # Sweep a coarse grid; silhouette computation is the cost driver.
    for k in range(k_min, min(k_max, max(k_min + 1, int(math.sqrt(n)))) + 1, 2):
        km = MiniBatchKMeans(n_clusters=k, batch_size=512, n_init=3, random_state=42)
        labels = km.fit_predict(Xs)
        if len(set(labels)) < 2:
            continue
        try:
            s = silhouette_score(Xs, labels, metric="cosine", sample_size=min(1000, Xs.shape[0]))
        except Exception:  # noqa: BLE001
            continue
        if s > best_score:
            best_score, best_k = s, k
    log.info("cluster.k_selected", k=best_k, silhouette=round(best_score, 3), n=n)
    return best_k


def cluster_texts(texts: Sequence[str], *, k_min: int = 4, k_max: int = 40):
    """Run TF-IDF + KMeans. Returns (vectorizer, model, X, labels)."""
    from sklearn.cluster import MiniBatchKMeans  # noqa: PLC0415

    vec, X = _vectorize(texts)
    k = _pick_k(X, k_min=k_min, k_max=k_max)
    km = MiniBatchKMeans(n_clusters=k, batch_size=1024, n_init=5, random_state=42)
    labels = km.fit_predict(X)
    return vec, km, X, labels


def top_terms_per_cluster(vec, km, *, top_n: int = 8) -> dict[int, list[str]]:
    """Most distinctive TF-IDF terms per cluster centroid."""
    feat_names = vec.get_feature_names_out()
    out: dict[int, list[str]] = {}
    for cid in range(km.cluster_centers_.shape[0]):
        center = km.cluster_centers_[cid]
        top_idx = center.argsort()[::-1][:top_n]
        out[cid] = [feat_names[i] for i in top_idx]
    return out


# ─── DB integration ─────────────────────────────────────────────────────

SELECT_DOCS_FOR_CLUSTERING = """
SELECT id::text, author_handle, body, title, created_utc
FROM documents
WHERE created_utc >= now() - ($1 || ' days')::interval
  AND COALESCE(body, '') <> ''
ORDER BY created_utc DESC
"""


async def fetch_corpus(pool: asyncpg.Pool, *, days: int = 30) -> list[dict]:
    async with pool.acquire() as c:
        rows = await c.fetch(SELECT_DOCS_FOR_CLUSTERING, str(days))
    return [dict(r) for r in rows]


def _doc_to_text(row: dict) -> str:
    parts = []
    if row.get("title"):
        parts.append(row["title"])
    if row.get("body"):
        parts.append(row["body"])
    return "\n".join(parts)


async def write_themes(
    pool: asyncpg.Pool,
    *,
    docs: list[dict],
    labels,
    top_terms: dict[int, list[str]],
    replace: bool = True,
) -> int:
    """Write the cluster output to `themes` and `theme_documents`.

    `replace=True` deletes existing themes first; clustering is non-incremental
    (it's cheap), so a full rewrite each run keeps theme ids meaningful.
    """
    import numpy as np  # noqa: PLC0415

    by_cluster: dict[int, list[dict]] = {}
    for doc, cid in zip(docs, labels):
        by_cluster.setdefault(int(cid), []).append(doc)

    async with pool.acquire() as c:
        async with c.transaction():
            if replace:
                await c.execute("DELETE FROM theme_documents")
                await c.execute("DELETE FROM themes")

            written = 0
            for cid, members in by_cluster.items():
                if not members:
                    continue
                terms = top_terms.get(cid, [])
                label = " · ".join(terms[:3]) if terms else f"cluster-{cid}"
                last_seen = max(m["created_utc"] for m in members)
                distinct_authors = len({m.get("author_handle") for m in members if m.get("author_handle")})

                theme_id = await c.fetchval(
                    """
                    INSERT INTO themes (label, summary, keywords, document_count,
                                        distinct_authors, last_seen_at, score, score_components)
                    VALUES ($1, NULL, $2::text[], $3, $4, $5, NULL, NULL)
                    RETURNING id
                    """,
                    label, terms, len(members), distinct_authors, last_seen,
                )
                # Bulk insert membership
                await c.executemany(
                    "INSERT INTO theme_documents (theme_id, document_id, weight) "
                    "VALUES ($1, $2::uuid, $3) ON CONFLICT DO NOTHING",
                    [(theme_id, m["id"], 1.0) for m in members],
                )
                written += 1
    return written


async def score_themes(pool: asyncpg.Pool) -> int:
    """Compute and store opportunity scores for every theme using the rubric in score.py."""
    from .score import ScoreInputs, score  # noqa: PLC0415

    async with pool.acquire() as c:
        themes = await c.fetch(
            """
            SELECT t.id::text, t.document_count, t.distinct_authors, t.last_seen_at,
                COALESCE((
                    SELECT SUM(rc.amount)
                    FROM revenue_claims rc
                    JOIN theme_documents td ON td.document_id = rc.document_id
                    WHERE td.theme_id = t.id AND rc.metric IN ('mrr','arr')
                ), 0) AS dollar_volume,
                COALESCE((
                    SELECT COUNT(DISTINCT m.product_id)
                    FROM mentions m
                    JOIN theme_documents td ON td.document_id = m.document_id
                    WHERE td.theme_id = t.id AND m.product_id IS NOT NULL
                ), 0) AS competitors
            FROM themes t
            """
        )
        now = datetime.now(tz=timezone.utc)
        n = 0
        for t in themes:
            recency_days = max(0.0, (now - t["last_seen_at"]).total_seconds() / 86400)
            inp = ScoreInputs(
                distinct_authors=t["distinct_authors"] or 1,
                documents=t["document_count"] or 1,
                recency_days=recency_days,
                revenue_dollar_volume=float(t["dollar_volume"] or 0),
                difficulty_1_5=3.0,        # default until phase 4 LLM rates it
                competitors=int(t["competitors"] or 0),
            )
            r = score(inp)
            await c.execute(
                "UPDATE themes SET score = $1, score_components = $2 WHERE id = $3::uuid",
                r.score, json.dumps(r.__dict__), t["id"],
            )
            n += 1
    return n


async def label_themes_with_llm(pool: asyncpg.Pool, *, sample_size: int = 8, model: str = "haiku") -> int:
    """For each theme without a real summary, ask Claude to name and summarize it.

    One CLI call per theme. With prompt caching this is ~$0.02/call after the first.
    """
    from .claude_cli import run_extraction  # noqa: PLC0415

    schema = {
        "type": "object",
        "properties": {
            "label": {"type": "string", "description": "<=6 words, no punctuation"},
            "summary": {"type": "string", "description": "1-2 sentences. What ties these docs together."},
        },
        "required": ["label", "summary"],
    }
    system = (
        "You are reading a sample of documents that an unsupervised clusterer grouped "
        "together. Find the common theme. Be concrete (a problem, a niche, a category) "
        "— not generic ('users discuss things'). Output JSON only."
    )

    async with pool.acquire() as c:
        themes = await c.fetch(
            "SELECT id::text, label FROM themes WHERE summary IS NULL"
        )
        n = 0
        for t in themes:
            sample = await c.fetch(
                """
                SELECT d.title, d.body
                FROM theme_documents td
                JOIN documents d ON d.id = td.document_id
                WHERE td.theme_id = $1::uuid
                ORDER BY d.score DESC NULLS LAST, d.created_utc DESC
                LIMIT $2
                """,
                t["id"], sample_size,
            )
            if not sample:
                continue
            blob = "\n\n---\n\n".join(
                f"{(s['title'] or '').strip()}\n{(s['body'] or '').strip()[:800]}"
                for s in sample
            )
            try:
                res = await run_extraction(
                    blob, model=model, system_prompt=system, schema=schema,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("cluster.label.fail", theme_id=t["id"], error=str(exc))
                continue
            so = res.structured_output or {}
            label = (so.get("label") or "").strip() or t["label"]
            summary = (so.get("summary") or "").strip()
            await c.execute(
                "UPDATE themes SET label = $1, summary = $2 WHERE id = $3::uuid",
                label[:120], summary[:1000], t["id"],
            )
            n += 1
            log.info("cluster.label.ok", theme_id=t["id"], label=label, cost=res.cost_usd)
    return n
