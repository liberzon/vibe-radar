"""Offline tests for the clustering algorithm — no DB, no LLM."""
import pytest

sklearn = pytest.importorskip("sklearn")

from analysis.cluster import cluster_texts, top_terms_per_cluster


def test_cluster_separates_obvious_topics():
    texts = (
        ["I just hit $3k MRR with my product for invoicing"] * 8 +
        ["My AI image generator is at $5k MRR now"] * 8 +
        ["How do I get my first paying customer for my newsletter?"] * 8 +
        ["Tips for landing the first 10 newsletter subscribers"] * 8
    )
    vec, km, X, labels = cluster_texts(texts, k_min=2, k_max=6)
    # Should produce at least 2 clusters and group similar texts together.
    assert len(set(labels)) >= 2
    # Same input string -> same cluster.
    assert labels[0] == labels[1]
    assert labels[8] == labels[9]


def test_top_terms_returns_distinctive_words():
    texts = (
        ["mrr saas invoicing dashboard"] * 6 +
        ["newsletter subscribers growth tips"] * 6
    )
    vec, km, X, labels = cluster_texts(texts, k_min=2, k_max=3)
    terms = top_terms_per_cluster(vec, km, top_n=3)
    # Each cluster's top terms should be drawn from its own input vocabulary.
    flat = {t for ts in terms.values() for t in ts}
    assert any(w in flat for w in ("saas", "mrr", "invoicing"))
    assert any(w in flat for w in ("newsletter", "subscribers", "growth"))
