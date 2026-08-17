from typing import Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Render provides postgres:// — the validator normalises it to postgresql+asyncpg://
    DATABASE_URL: str = "postgresql+asyncpg://mindspread:mindspread@localhost:5432/mindspread"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalise_db_url(cls, v: str) -> str:
        """
        Render's Postgres connectionString starts with postgres:// which
        SQLAlchemy 2.0 + asyncpg rejects. Normalise on load so the rest of
        the codebase never has to care.
        """
        if v.startswith("postgres://"):
            return "postgresql+asyncpg://" + v[len("postgres://"):]
        if v.startswith("postgresql://") and "+asyncpg" not in v:
            return "postgresql+asyncpg://" + v[len("postgresql://"):]
        return v

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # Auth
    JWT_SECRET: str = "insecure-dev-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS / app
    FRONTEND_ORIGIN: str = "http://localhost:5173"
    ENVIRONMENT: str = "development"
    MAX_UPLOAD_MB: int = 50

    # AI
    ANTHROPIC_API_KEY: Optional[str] = None

    # Observability
    SENTRY_DSN: Optional[str] = None

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def sync_database_url(self) -> str:
        """psycopg2 URL for Alembic (sync driver)."""
        return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)


settings = Settings()
