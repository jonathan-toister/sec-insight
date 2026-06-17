"""Application settings, loaded from environment (.env).

Uses pydantic-settings so config is typed and validated at startup.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM / embeddings ---
    anthropic_api_key: str = ""          # generation (Claude)
    openai_api_key: str = ""             # embeddings only (text-embedding-3-small)
    chat_model: str = "claude-sonnet-4-6"
    hyde_model: str = "claude-haiku-4-5-20251001"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    # --- Database ---
    database_url: str = "postgresql+psycopg://sec:sec@localhost:5432/sec"

    # --- Redis (arq job queue) ---
    redis_url: str = "redis://localhost:6379"

    # --- SEC EDGAR ---
    # SEC requires a descriptive User-Agent: "Name email" — see SPEC.md.
    sec_user_agent: str = "sec-insight you@example.com"

    # --- Market data (Phase 3) ---
    market_data_api_key: str = ""


settings = Settings()  # import this object elsewhere
