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


settings = Settings()
