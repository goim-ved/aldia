from functools import lru_cache
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_NAME: str = Field(default="async-webhook-engine", description="Application name")
    APP_ENV: Literal["development", "testing", "production"] = Field(
        default="development", description="Current environment mode"
    )
    DEBUG: bool = Field(default=True, description="Debug mode flag")
    PORT: int = Field(default=8000, description="Web server port")
    HOST: str = Field(default="0.0.0.0", description="Web server host")

    SECRET_KEY: str = Field(
        default="change-this-super-secret-key-in-production-use-openssl-rand-hex-32",
        description="Secret key for JWT token and signature generation",
    )
    ALGORITHM: str = Field(default="HS256", description="JWT hashing algorithm")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=60, description="Access token expiration time in minutes"
    )

    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://webhook_user:webhook_password@localhost:5432/webhook_db",
        description="Async PostgreSQL connection URL",
    )
    SYNC_DATABASE_URL: str = Field(
        default="postgresql://webhook_user:webhook_password@localhost:5432/webhook_db",
        description="Sync PostgreSQL connection URL for Celery worker & Alembic",
    )

    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for caching and rate limiting",
    )
    CELERY_BROKER_URL: str = Field(
        default="redis://localhost:6379/1",
        description="Celery broker connection URL",
    )
    CELERY_RESULT_BACKEND: str = Field(
        default="redis://localhost:6379/2",
        description="Celery result backend URL",
    )

    RATE_LIMIT_REQUESTS: int = Field(
        default=60, description="Allowed request count per sliding window"
    )
    RATE_LIMIT_WINDOW_SECONDS: int = Field(
        default=60, description="Sliding window duration in seconds"
    )

    WEBHOOK_TIMEOUT_SECONDS: int = Field(
        default=10, description="HTTP timeout for webhook delivery in seconds"
    )
    WEBHOOK_MAX_RETRIES: int = Field(
        default=3, description="Maximum retry attempts for failed webhook dispatches"
    )
    WEBHOOK_RETRY_DELAYS: list[int] = Field(
        default=[5, 15, 45],
        description="Backoff delay intervals in seconds for delivery retries",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
