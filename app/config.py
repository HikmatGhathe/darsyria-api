from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str

    # Application
    app_env: str = "development"
    secret_key: str

    # JWT
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 10080

    # Magic link
    magic_link_expiration_minutes: int = 15
    frontend_url: str = "http://localhost:3000"

    # Ollama
    ollama_api_url: str = ""
    ollama_api_key: str = ""
    ollama_model: str = "gemma2:27b"

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

    # Resend email service
    resend_api_key: str
    email_from: str
    email_from_name: str = "DarSyria"


settings = Settings()
