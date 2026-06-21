-- Phase 6 migration — idempotent, safe to re-run.
-- Also fixes pre-Phase-6 schema drift: adds columns the ORM model expects that
-- were missing from the legacy DB, and makes legacy-only columns nullable so
-- ORM inserts (which don't set them) don't fail.

-- ─── companies ───────────────────────────────────────────────────────────────

-- Pre-Phase-6 columns the ORM model expects but may be missing in older DBs
ALTER TABLE companies ADD COLUMN IF NOT EXISTS sic TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS sic_description TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS state_of_incorporation TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS exchanges TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS entity_type TEXT;

-- Phase 6 additions
ALTER TABLE companies ADD COLUMN IF NOT EXISTS sector TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS industry TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS fiscal_year_end TEXT;

-- ─── filings ─────────────────────────────────────────────────────────────────

-- Legacy columns (cik, company, ticker) were added directly to filings in an
-- earlier schema before the companies table was normalised. Make them nullable
-- so the ORM (which uses company_id FK instead) can INSERT without errors.
ALTER TABLE filings ALTER COLUMN cik DROP NOT NULL;
ALTER TABLE filings ALTER COLUMN company DROP NOT NULL;

-- Pre-Phase-6 ORM column that may be missing
ALTER TABLE filings ADD COLUMN IF NOT EXISTS company_id BIGINT
    REFERENCES companies(id);

-- Phase 6 additions
ALTER TABLE filings ADD COLUMN IF NOT EXISTS period_of_report DATE;
ALTER TABLE filings ADD COLUMN IF NOT EXISTS accession_number TEXT;
-- DEFAULT populates existing rows as 'sec_filing' immediately on ADD COLUMN
ALTER TABLE filings ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'sec_filing';

-- Idempotent URL unique constraint (ORM uses url as the dedup key)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'filings'::regclass
          AND contype = 'u'
          AND conname = 'uq_filings_url'
    ) THEN
        ALTER TABLE filings ADD CONSTRAINT uq_filings_url UNIQUE (url);
    END IF;
END $$;

-- ─── indexes ─────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS ix_filings_company_period ON filings (company_id, period_of_report);
CREATE INDEX IF NOT EXISTS ix_chunks_filing_id ON chunks (filing_id);

-- HNSW index (in init_db.sql for new installs; repeated here for existing DBs)
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx ON chunks USING hnsw (embedding vector_cosine_ops);
