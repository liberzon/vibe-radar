"""Cheap first-pass extraction using regex.

Catches the easy 80%: explicit MRR/ARR claims, user counts, and obvious product
mentions (URLs, "<Name> by <handle>" patterns). LLM extraction handles the rest.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

# "$3.4k MRR", "$10K/mo", "12k/month", "$1.2M ARR"
_MONEY = re.compile(
    r"""
    (?P<currency>[\$€£])?\s*
    (?P<amount>\d{1,3}(?:[.,]\d+)?)
    \s*
    (?P<scale>[kKmMbB])?
    \s*
    (?:/\s*(?:mo|month|year|yr)|\s*(?:MRR|ARR|/mo|/month|/yr|per\s+month|per\s+year))
    """,
    re.VERBOSE | re.IGNORECASE,
)

_USERS = re.compile(
    r"\b(?P<count>\d{1,3}(?:[.,]\d+)?)\s*(?P<scale>[kKmM])?\s*(?:paying\s+)?(?:users|customers|subscribers)\b",
    re.IGNORECASE,
)

_SCALE = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


@dataclass
class RevenueClaim:
    metric: str        # 'mrr' | 'arr' | 'users' | 'revenue_total'
    amount: float
    currency: str | None
    quote: str
    span: tuple[int, int]
    confidence: float  # 0..1, regex confidence


def extract_revenue_claims(text: str) -> list[RevenueClaim]:
    if not text:
        return []
    out: list[RevenueClaim] = []

    for m in _MONEY.finditer(text):
        amt = float(m.group("amount").replace(",", "."))
        scale = m.group("scale")
        if scale:
            amt *= _SCALE[scale.lower()]
        currency = m.group("currency")
        full = m.group(0).lower()
        if "arr" in full or "/yr" in full or "year" in full:
            metric = "arr"
        elif "mrr" in full or "/mo" in full or "month" in full:
            metric = "mrr"
        else:
            metric = "revenue_total"
        out.append(RevenueClaim(
            metric=metric,
            amount=amt,
            currency=currency or None,
            quote=text[max(0, m.start()-30): m.end()+30],
            span=(m.start(), m.end()),
            confidence=0.7,
        ))

    for m in _USERS.finditer(text):
        amt = float(m.group("count").replace(",", "."))
        scale = m.group("scale")
        if scale:
            amt *= _SCALE[scale.lower()]
        out.append(RevenueClaim(
            metric="users",
            amount=amt,
            currency=None,
            quote=text[max(0, m.start()-30): m.end()+30],
            span=(m.start(), m.end()),
            confidence=0.6,
        ))

    return out


_HOMEPAGE = re.compile(r"https?://(?:www\.)?([a-z0-9][a-z0-9-]+\.[a-z]{2,}(?:/[\w\-./]*)?)", re.IGNORECASE)


def extract_homepage_mentions(text: str) -> list[tuple[str, tuple[int, int]]]:
    """Return (host, span) for likely product homepages — naive; LLM filters later."""
    blacklist = {"github.com", "twitter.com", "x.com", "reddit.com", "ycombinator.com",
                 "youtube.com", "youtu.be", "imgur.com", "i.redd.it", "wikipedia.org",
                 "medium.com", "linkedin.com", "facebook.com", "instagram.com"}
    out: list[tuple[str, tuple[int, int]]] = []
    if not text:
        return out
    for m in _HOMEPAGE.finditer(text):
        host = m.group(1).split("/")[0].lower()
        if host in blacklist:
            continue
        out.append((host, (m.start(), m.end())))
    return out
