-- Track which documents have been LLM-processed (for idempotent re-runs).
CREATE TABLE IF NOT EXISTS extraction_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    prompt_version  TEXT NOT NULL,
    extractor       TEXT NOT NULL,           -- 'claude-cli' | 'sdk' | 'regex'
    model           TEXT,
    status          TEXT NOT NULL CHECK (status IN ('ok','failed','skipped')),
    cost_usd        NUMERIC,
    duration_ms     INTEGER,
    raw             JSONB,                    -- structured_output as returned
    error           TEXT,
    extracted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, prompt_version, extractor)
);
CREATE INDEX IF NOT EXISTS extraction_runs_document_idx ON extraction_runs (document_id);
