-- Phase 2: unified multi-source schema.
-- Each source collector continues to write its native tables (e.g. posts, comments)
-- AND emits rows into `documents`. Analysis layers operate on `documents` only.

CREATE TABLE IF NOT EXISTS documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source          TEXT NOT NULL CHECK (source IN ('reddit','hn','github','producthunt','youtube','rss')),
    source_id       TEXT NOT NULL,                  -- platform-native id (e.g. t3_abc123, hn:item:123)
    kind            TEXT NOT NULL,                  -- 'post' | 'comment' | 'release' | 'launch' | ...
    parent_source_id TEXT,                          -- e.g. comment's parent
    author_handle   TEXT,
    title           TEXT,
    body            TEXT,
    url             TEXT,
    language        TEXT,
    score           INTEGER,
    created_utc     TIMESTAMPTZ NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_ref         TEXT,                           -- pointer to raw_payloads or object store
    UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS documents_source_created_idx ON documents (source, created_utc DESC);
CREATE INDEX IF NOT EXISTS documents_created_idx ON documents (created_utc DESC);

-- Canonical product/tool entities discovered in the corpus.
CREATE TABLE IF NOT EXISTS products (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name     TEXT NOT NULL UNIQUE,
    aliases            TEXT[] NOT NULL DEFAULT '{}',
    homepage           TEXT,
    github_url         TEXT,
    category           TEXT,
    pricing_model      TEXT,                        -- 'free' | 'freemium' | 'subscription' | 'one-time' | 'unknown'
    first_mentioned_at TIMESTAMPTZ,
    last_mentioned_at  TIMESTAMPTZ,
    mention_count      INTEGER NOT NULL DEFAULT 0,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Mention = one occurrence of a product in a document.
CREATE TABLE IF NOT EXISTS mentions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id   UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    product_id    UUID REFERENCES products(id) ON DELETE SET NULL,
    mention_kind  TEXT NOT NULL CHECK (mention_kind IN ('product','service','tool','idea')),
    surface_text  TEXT NOT NULL,
    normalized_name TEXT,                            -- before linking to products
    span_start    INTEGER,
    span_end      INTEGER,
    confidence    REAL NOT NULL,
    extracted_via TEXT NOT NULL CHECK (extracted_via IN ('regex','llm','manual')),
    extracted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, surface_text, span_start)
);
CREATE INDEX IF NOT EXISTS mentions_product_idx ON mentions (product_id);
CREATE INDEX IF NOT EXISTS mentions_document_idx ON mentions (document_id);

-- Revenue / traction claims found in documents (e.g. "$3k MRR", "100 paying users").
CREATE TABLE IF NOT EXISTS revenue_claims (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id   UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    product_id    UUID REFERENCES products(id) ON DELETE SET NULL,
    claim_text    TEXT NOT NULL,                    -- raw quote
    metric        TEXT NOT NULL CHECK (metric IN ('mrr','arr','users','revenue_total','profit','traffic','other')),
    amount        NUMERIC,
    currency      TEXT,                             -- 'USD','EUR',...
    asof_date     DATE,
    claim_type    TEXT NOT NULL CHECK (claim_type IN ('self-reported','inferred','third-party')),
    confidence    REAL NOT NULL,
    extracted_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS revenue_claims_product_idx ON revenue_claims (product_id);
CREATE INDEX IF NOT EXISTS revenue_claims_metric_idx ON revenue_claims (metric, asof_date);

-- Themes / clusters: emergent groupings of documents around a need or topic.
CREATE TABLE IF NOT EXISTS themes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label           TEXT NOT NULL,                  -- short human-readable label
    summary         TEXT,                           -- LLM-written description
    keywords        TEXT[] NOT NULL DEFAULT '{}',
    document_count  INTEGER NOT NULL DEFAULT 0,
    distinct_authors INTEGER NOT NULL DEFAULT 0,
    last_seen_at    TIMESTAMPTZ,
    score           REAL,                           -- opportunity score (see analysis/score.py)
    score_components JSONB,                         -- {demand, wtp, difficulty, competition}
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS theme_documents (
    theme_id     UUID NOT NULL REFERENCES themes(id) ON DELETE CASCADE,
    document_id  UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    weight       REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (theme_id, document_id)
);

-- Architectural proposals (phase 4 — written by Claude given a theme).
CREATE TABLE IF NOT EXISTS proposals (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    theme_id     UUID REFERENCES themes(id) ON DELETE SET NULL,
    title        TEXT NOT NULL,
    problem      TEXT,
    target_user  TEXT,
    differentiation TEXT,
    mvp_features TEXT[],
    architecture TEXT,                              -- markdown
    stack        TEXT[],
    cost_low_usd NUMERIC,
    cost_high_usd NUMERIC,
    risks        TEXT,
    status       TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','rejected','built','deployed')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at   TIMESTAMPTZ
);
