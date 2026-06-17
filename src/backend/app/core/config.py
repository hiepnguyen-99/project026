from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/eduvault"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # MinIO
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "eduvault"
    MINIO_SECURE: bool = False

    # JWT
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24

    # LLM
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 1536  # text-embedding-3-small; ≤2000 để pgvector HNSW chạy
    LLM_MODEL: str = "gpt-4o-mini"

    # LangSmith
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "eduvault"
    LANGCHAIN_TRACING_V2: bool = False

    # App
    APP_ENV: str = "development"
    CORS_ORIGINS: str = "http://localhost:3000"

    @property
    def async_database_url(self) -> str:
        """URL dùng cho SQLAlchemy async (asyncpg driver)."""
        return self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)


settings = Settings()
