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

    # --- API authentication (scripts / CLI) ---
    api_key: str = ""  # X-API-Key header; all non-health endpoints require this or a session cookie

    # --- Browser session auth ---
    login_password: str = ""        # password for POST /auth/login
    jwt_secret: str = ""            # signs session cookies; generate with secrets.token_hex(32)
    jwt_expire_days: int = 7
    # Comma-separated allowed FE origins, e.g. "https://app.example.com,http://localhost:3000"
    allowed_origins: str = ""
    cookie_secure: bool = True      # set COOKIE_SECURE=false for local HTTP dev

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()  # import this object elsewhere
