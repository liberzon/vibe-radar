"""Opportunity scoring for clustered themes.

Inputs (per theme):
  - distinct_authors: int       # how many unique people raised this
  - documents: int              # total mentions
  - recency_days: float         # days since most recent mention
  - revenue_dollar_volume: float # sum of MRR/ARR/total claims associated with this theme
  - difficulty_1_5: float       # LLM-rated build complexity (lower = easier)
  - competitors: int            # count of distinct existing products in cluster

Output: a single normalized score in [0, ∞), and component scores for transparency.

Tweak weights in `score_components.json` once we have signal — these are seeds.
"""
from __future__ import annotations
import math
from dataclasses import dataclass


@dataclass
class ScoreInputs:
    distinct_authors: int
    documents: int
    recency_days: float
    revenue_dollar_volume: float
    difficulty_1_5: float    # 1 (trivial) to 5 (huge)
    competitors: int


@dataclass
class ScoreOutput:
    score: float
    demand: float
    wtp: float
    difficulty: float
    competition: float


def score(inp: ScoreInputs) -> ScoreOutput:
    # Demand: log of distinct authors × log of volume × recency decay (half-life 30d)
    decay = math.pow(0.5, inp.recency_days / 30.0)
    demand = (
        math.log1p(inp.distinct_authors) *
        math.log1p(inp.documents) *
        decay
    )
    # Willingness to pay: log of dollars in adjacent claims (1 = $0, 8 ≈ $3k, 14 ≈ $1M)
    wtp = math.log1p(max(inp.revenue_dollar_volume, 0))
    # Difficulty (penalty): 1.0 (trivial) ... 5.0 (huge)
    difficulty = max(1.0, inp.difficulty_1_5)
    # Competition (penalty): 1 (no competitors) ... grows linearly
    competition = 1.0 + 0.4 * inp.competitors

    raw = (demand * (1.0 + wtp)) / (difficulty * competition)
    return ScoreOutput(
        score=round(raw, 3),
        demand=round(demand, 3),
        wtp=round(wtp, 3),
        difficulty=round(difficulty, 3),
        competition=round(competition, 3),
    )
