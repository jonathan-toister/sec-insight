-- Runs automatically the first time the Postgres container starts.
-- Enables pgvector. Table creation can live here or in SQLAlchemy models.
CREATE EXTENSION IF NOT EXISTS vector;

-- Reference schema (Claude Code can generate the real version via SQLAlchemy):
--
-- CREATE TABLE filings (
--   id           BIGSERIAL PRIMARY KEY,
--   cik          TEXT NOT NULL,
--   company      TEXT NOT NULL,
--   ticker       TEXT,
--   form_type    TEXT NOT NULL,        -- '10-K', '10-Q'
--   fiscal_year  INT,
--   url          TEXT NOT NULL,
--   filed_at     DATE,
--   UNIQUE (url)
-- );
--
-- CREATE TABLE chunks (
--   id          BIGSERIAL PRIMARY KEY,
--   filing_id   BIGINT REFERENCES filings(id) ON DELETE CASCADE,
--   chunk_index INT NOT NULL,
--   section     TEXT,
--   text        TEXT NOT NULL,
--   embedding   VECTOR(1536)
-- );
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);
