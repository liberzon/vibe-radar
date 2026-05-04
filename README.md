# vibe-radar

A compliance-first, **read-only** ingestion pipeline for public posts and
comments from official APIs (Reddit OAuth Data API, Hacker News public APIs).
Records are normalized into a private local Postgres database for personal,
non-commercial research and analysis.

## What it does

- Authenticates to Reddit via the official OAuth 2.0 Data API using a script
  app (client credentials grant). Reads listings (`/r/{sub}/{listing}`),
  search, and comment trees only. Never posts, votes, comments, messages, or
  otherwise interacts with users.
- Authenticates to Hacker News' public Firebase + Algolia APIs (no auth
  required, polite throttle).
- Normalizes everything into a unified `documents` table; runs offline
  extraction (regex + optional LLM) and TF-IDF clustering for analysis.

## What it does not do

- No HTML scraping, no headless browsers, no IP rotation, no CAPTCHA bypass.
- No interaction with users (no posts, votes, comments, DMs).
- No bypassing rate limits or robots.txt.
- No public redistribution of collected content.
- No ML training on collected content.
- No deanonymization or external identity enrichment.

## Compliance posture

- Descriptive `User-Agent` set on every request, per platform guidelines.
- Reads `X-Ratelimit-*` headers after every Reddit response and proactively
  backs off; stays well below the free-tier limit.
- Honors deletions: items returning `[deleted]` / `[removed]` are tombstoned
  in storage within 24h; downstream views filter them out.
- Honors per-subreddit bot/automation rules (excludes any subreddit that
  forbids automated reads in its rules).
- Per-source compliance notes in `compliance/SOURCES.md`.

## How to run

```bash
pip install -e ".[cluster,praw]"
cp .env.example .env                                 # fill in REDDIT_CLIENT_ID/SECRET/USER_AGENT
cp config/sources.example.yaml config/sources.yaml   # then customize
make db && make migrate
vibe-radar collect
vibe-radar status
```

The operational `config/sources.yaml` is gitignored — use
`config/sources.example.yaml` as a template.

## Architecture (one-liner)

Source collectors → unified `documents` table → regex/LLM extraction →
TF-IDF clustering → opportunity scoring.

## Project status

Personal research project. Not a product, not a service, not for commercial
use. No support guarantees.

## License

Source code: MIT (see `LICENSE`). Collected content remains under the
respective platform's terms; this repository ships **only the code**, never
collected data.
