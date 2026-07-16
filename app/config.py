from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str

    # Application
    app_env: str = "development"
    secret_key: str

    # JWT access token (short-lived; lives in an httpOnly cookie)
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 30

    # Refresh token (long-lived, opaque, rotated on use; httpOnly cookie scoped to /auth)
    refresh_token_expiration_days: int = 30

    @property
    def cookie_secure(self) -> bool:
        return self.app_env == "production"

    # Magic link
    magic_link_expiration_minutes: int = 15
    frontend_url: str = "http://localhost:3000"

    # CORS — comma-separated list of allowed origins
    allowed_origins: str = "http://localhost:3000"

    @property
    def cors_allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    # Chat LLM — any OpenAI-compatible provider (Groq, OpenAI, Together,
    # OpenRouter, or Ollama's own /v1 endpoint). Set LLM_BASE_URL to the
    # provider's base, e.g. https://api.groq.com/openai/v1
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    # Legacy Ollama vars — deprecated aliases kept so existing deployments keep
    # working. The LLM_* settings above take precedence when set.
    ollama_api_url: str = ""
    ollama_api_key: str = ""
    ollama_model: str = "gemma2:27b"

    @property
    def chat_base_url(self) -> str:
        """OpenAI-compatible base URL for the chat model (LLM_* wins)."""
        return (self.llm_base_url or self.ollama_api_url).rstrip("/")

    @property
    def chat_api_key(self) -> str:
        return self.llm_api_key or self.ollama_api_key

    @property
    def chat_model(self) -> str:
        return self.llm_model or self.ollama_model

    # RAG / Embeddings
    article_source_dir: str = "content/articles"
    embedding_model: str = "intfloat/multilingual-e5-large"
    embedding_dimensions: int = 1024

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    # Cloudflare R2 object storage
    r2_account_id: str
    r2_access_key_id: str
    r2_secret_access_key: str
    r2_bucket_name: str
    r2_endpoint_url: str
    r2_public_url: str
    # Optional separate, NON-public bucket for sensitive verification documents
    # (deeds, IDs, business licenses). Strongly recommended in production so
    # these are never reachable via the public bucket domain. Falls back to the
    # main bucket when empty (documents then rely on unguessable keys only).
    r2_private_bucket_name: str = ""

    # Resend email service
    resend_api_key: str
    email_from: str
    email_from_name: str = "DarSyria"

    # Sentry error monitoring. Leave SENTRY_DSN empty to disable entirely
    # (the SDK is never initialized, so this is a complete no-op locally).
    sentry_dsn: str = ""
    # Fraction of requests traced for performance (0.0–1.0). Keep low in prod.
    sentry_traces_sample_rate: float = 0.0


settings = Settings()
