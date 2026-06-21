-- Phase 7: add section-aware metadata to chunks
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS item_number TEXT;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS heading TEXT;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS is_table BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS fiscal_year INTEGER;

CREATE INDEX IF NOT EXISTS ix_chunks_item_number ON chunks (item_number)
    WHERE item_number IS NOT NULL;
