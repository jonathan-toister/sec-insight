-- One-time setup: enables pgvector extension.
-- All tables and indexes are owned by SQLAlchemy models (app/models.py) via create_all().
-- Run this once against a fresh database before starting the app.
CREATE EXTENSION IF NOT EXISTS vector;
