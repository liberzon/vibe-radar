-- reddit-collector schema (Postgres 14+)
--
-- All Reddit IDs are stored as their fullname (e.g. t3_abc123, t1_xyz789).
-- All timestamps are TIMESTAMPTZ. UTC everywhere.

CREATE EXTENSION IF NOT EXISTS pgcrypto;     -- gen_random_uuid()
-- CREATE EXTENSION IF NOT EXISTS vector;     -- enable when adding embeddings

-- ─────────────────────────────────────────────────────────────────
-- subreddits
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS subreddits (
    name              TEXT PRIMARY KEY,            -- lowercased, no /r/ prefix
    display_name      TEXT,
    title             TEXT,
    public_description TEXT,
    subscribers       INTEGER,
    over18            BOOLEAN,
    created_utc       TIMESTAMPTZ,
    last_synced_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────────
-- authors  (treat as PII; gate downstream access)
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS authors (
    id            TEXT PRIMARY KEY,                -- t2_*
    username      TEXT UNIQUE,
    created_utc   TIMESTAMPTZ,
    is_suspended  BOOLEAN,
    is_deleted    BOOLEAN NOT NULL DEFAULT FALSE,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────────
-- posts
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS posts (
    id                 TEXT PRIMARY KEY,           -- t3_*
    subreddit          TEXT NOT NULL REFERENCES subreddits(name) ON DELETE CASCADE,
    author_id          TEXT REFERENCES authors(id),  -- nullable for [deleted]
    author_username    TEXT,                       -- denormalized for convenience
    title              TEXT NOT NULL,
    selftext           TEXT,
    url                TEXT,
    permalink          TEXT,
    domain             TEXT,
    is_self            BOOLEAN,
    over18             BOOLEAN,
    spoiler            BOOLEAN,
    stickied           BOOLEAN,
    locked             BOOLEAN,
    removed            BOOLEAN NOT NULL DEFAULT FALSE,
    score              INTEGER,
    upvote_ratio       REAL,
    num_comments       INTEGER,
    created_utc        TIMESTAMPTZ NOT NULL,
    edited_utc         TIMESTAMPTZ,
    deleted_at         TIMESTAMPTZ,
    content_hash       TEXT NOT NULL,
    first_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_refreshed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS posts_subreddit_created_idx
    ON posts (subreddit, created_utc DESC);
CREATE INDEX IF NOT EXISTS posts_author_idx
    ON posts (author_id);
CREATE INDEX IF NOT EXISTS posts_content_hash_idx
    ON posts (content_hash);
CREATE INDEX IF NOT EXISTS posts_last_refreshed_idx
    ON posts (last_refreshed_at);

-- ─────────────────────────────────────────────────────────────────
-- comments
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS comments (
    id                 TEXT PRIMARY KEY,           -- t1_*
    post_id            TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    parent_id          TEXT NOT NULL,              -- t1_* or t3_* (the post)
    subreddit          TEXT NOT NULL,
    author_id          TEXT REFERENCES authors(id),
    author_username    TEXT,
    body               TEXT,
    score              INTEGER,
    depth              INTEGER NOT NULL DEFAULT 0,
    removed            BOOLEAN NOT NULL DEFAULT FALSE,
    created_utc        TIMESTAMPTZ NOT NULL,
    edited_utc         TIMESTAMPTZ,
    deleted_at         TIMESTAMPTZ,
    content_hash       TEXT NOT NULL,
    first_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS comments_post_idx          ON comments (post_id);
CREATE INDEX IF NOT EXISTS comments_parent_idx        ON comments (parent_id);
CREATE INDEX IF NOT EXISTS comments_subreddit_created_idx ON comments (subreddit, created_utc DESC);
CREATE INDEX IF NOT EXISTS comments_author_idx        ON comments (author_id);
CREATE INDEX IF NOT EXISTS comments_content_hash_idx  ON comments (content_hash);

-- ─────────────────────────────────────────────────────────────────
-- ingestion_jobs  (Postgres-backed queue with SKIP LOCKED)
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind           TEXT NOT NULL CHECK (kind IN ('listing','comments','search','refresh')),
    source_key     TEXT NOT NULL,                  -- e.g. "subreddit:programming:new" or "post:t3_abc"
    cursor         TEXT,                           -- "after" fullname / search cursor
    state          TEXT NOT NULL DEFAULT 'pending'
                       CHECK (state IN ('pending','running','done','failed','dead')),
    attempts       INTEGER NOT NULL DEFAULT 0,
    last_error     TEXT,
    scheduled_for  TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at     TIMESTAMPTZ,
    finished_at    TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ingestion_jobs_dispatch_idx
    ON ingestion_jobs (state, scheduled_for)
    WHERE state IN ('pending','running');

-- High-water marks per source (for incremental sync)
CREATE TABLE IF NOT EXISTS source_state (
    source_key       TEXT PRIMARY KEY,
    high_water_mark  TIMESTAMPTZ,
    last_fullname    TEXT,
    last_run_at      TIMESTAMPTZ,
    last_status      TEXT
);

-- ─────────────────────────────────────────────────────────────────
-- raw_payloads  (append-only audit log; small payloads inline,
-- large payloads referenced by URI in object storage)
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS raw_payloads (
    id           BIGSERIAL PRIMARY KEY,
    endpoint     TEXT NOT NULL,
    params_hash  TEXT NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    status_code  INTEGER NOT NULL,
    payload_uri  TEXT,                              -- s3://bucket/key  (preferred)
    payload      JSONB                               -- inline fallback for small bodies
);
CREATE INDEX IF NOT EXISTS raw_payloads_endpoint_time_idx
    ON raw_payloads (endpoint, fetched_at DESC);

-- ─────────────────────────────────────────────────────────────────
-- Helper view: live (non-deleted) content for downstream consumers
-- ─────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW posts_live AS
    SELECT * FROM posts WHERE deleted_at IS NULL AND removed = FALSE;

CREATE OR REPLACE VIEW comments_live AS
    SELECT * FROM comments WHERE deleted_at IS NULL AND removed = FALSE;
