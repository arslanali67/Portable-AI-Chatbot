from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-secret-change-me-0123456789abcdef"


class Settings(BaseSettings):
    """Application settings, loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "PortableAI API"
    app_version: str = "0.1.0"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    environment: str = "development"

    # Security
    jwt_secret: str = Field(..., description="JWT signing secret — set in .env")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Database
    database_url: str = Field(
        ...,
        description="Async SQLAlchemy database URL, e.g. postgresql+asyncpg://user:pass@host:5432/portableai",
    )

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # CORS + trusted hosts
    cors_origins: list[str] = ["http://localhost:3000"]
    trusted_hosts: list[str] = []

    # Logging
    log_level: str = "INFO"

    # Request limits
    max_request_bytes: int = 1024 * 1024

    # OpenAI-compatible provider (credentials from environment only)
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_timeout: float = 60.0
    openai_model: str = "gpt-4o-mini"

    # Embeddings (fake default; openai enabled when key present)
    embedding_provider_id: str = "fake"
    embedding_model_id: str = "fake-embed-v1"
    embedding_dimensions: int = 384
    chunk_size: int = 500
    chunk_overlap: int = 50

    # OpenAI-compatible embeddings (credentials from environment only)
    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_timeout: float = 30.0

    # RAG runtime
    rag_top_k: int = 5
    rag_max_context_chars: int = 8000

    # File ingestion limits
    max_file_size_bytes: int = 10 * 1024 * 1024
    max_extracted_text_chars: int = 100_000

    # URL ingestion
    url_fetch_timeout: float = 15.0
    url_max_redirects: int = 5
    url_max_response_bytes: int = 5 * 1024 * 1024
    url_user_agent: str = "PortableAI-KnowledgeBot/0.1"
    url_respect_robots: bool = True

    # Public widget
    widget_session_ttl_hours: int = 24
    widget_rate_limit_messages: int = 30
    widget_rate_limit_window_seconds: int = 3600
    widget_placeholder_user_name: str = "Widget Visitor"

    @field_validator("environment")
    @classmethod
    def environment_valid(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"development", "test", "production"}:
            raise ValueError(f"invalid environment: {value}")
        return normalized

    @model_validator(mode="after")
    def fail_fast_production(self) -> "Settings":
        """Fail fast on unsafe production configuration at construction time."""
        if not self.is_production:
            return self
        if not self.jwt_secret or self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < 32:
            raise ValueError("Production requires a strong JWT_SECRET (>= 32 chars, not the dev default).")
        if not self.cors_origins:
            raise ValueError("Production requires CORS_ORIGINS to be explicitly configured.")
        if not self.trusted_hosts:
            raise ValueError("Production requires TRUSTED_HOSTS to be explicitly configured.")
        if not self.database_url.startswith(("postgresql+asyncpg://", "postgresql://")):
            raise ValueError("Production requires a PostgreSQL DATABASE_URL.")
        if self.debug:
            raise ValueError("Production must not enable DEBUG.")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()