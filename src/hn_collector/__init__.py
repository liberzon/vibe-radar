"""Hacker News collector via the official Firebase API + Algolia search.

References:
  https://github.com/HackerNews/API           (Firebase, public, read-only, no auth)
  https://hn.algolia.com/api                  (Algolia search over HN, public)

Both APIs are public and explicitly intended for programmatic use. We still
identify ourselves with a User-Agent and avoid hammering them — default 2 RPS.
"""
