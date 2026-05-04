from analysis.regex_pass import extract_revenue_claims, extract_homepage_mentions
from analysis.score import ScoreInputs, score


def test_regex_extracts_mrr():
    txt = "Hit $3.4k MRR last month after launching on PH."
    claims = extract_revenue_claims(txt)
    assert len(claims) == 1
    assert claims[0].metric == "mrr"
    assert claims[0].amount == 3400


def test_regex_extracts_users():
    txt = "We have 12k paying customers now."
    claims = extract_revenue_claims(txt)
    assert any(c.metric == "users" and c.amount == 12000 for c in claims)


def test_homepage_mentions_skip_blacklist():
    txt = "I built it at https://myapp.io/ and posted on https://reddit.com/r/SomeSub"
    hosts = [h for h, _ in extract_homepage_mentions(txt)]
    assert "myapp.io" in hosts
    assert "reddit.com" not in hosts


def test_score_monotonic_in_demand():
    s1 = score(ScoreInputs(distinct_authors=2, documents=2, recency_days=1,
                           revenue_dollar_volume=0, difficulty_1_5=3, competitors=1))
    s2 = score(ScoreInputs(distinct_authors=200, documents=200, recency_days=1,
                           revenue_dollar_volume=0, difficulty_1_5=3, competitors=1))
    assert s2.score > s1.score


def test_score_penalizes_competition():
    base = ScoreInputs(distinct_authors=50, documents=80, recency_days=2,
                       revenue_dollar_volume=10_000, difficulty_1_5=3, competitors=1)
    crowded = ScoreInputs(**{**base.__dict__, "competitors": 20})
    assert score(crowded).score < score(base).score
