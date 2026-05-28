from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    APP_NAME: str = "CRM MVP"
    DEBUG: bool = False
    BASE_URL: str = "http://localhost:8000"

    # Database (postgresql+asyncpg:// required)
    DATABASE_URL: str
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Security
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24h
    ALGORITHM: str = "HS256"

    # Telegram webhook
    # TELEGRAM_BOT_TOKEN is used only by local/dev seed scripts. Runtime
    # message sending reads bot tokens from the bots table.
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    # TELEGRAM_PROJECT_ID — UUID of the project that owns this bot's conversations.
    # Must be set before the webhook is registered; the endpoint returns 200 but
    # skips processing if the value is missing (prevents silent data loss).
    TELEGRAM_PROJECT_ID: Optional[str] = None
    # TELEGRAM_WEBHOOK_SECRET — optional token set via setWebhook(secret_token=...).
    # If set, every incoming request is validated against
    # X-Telegram-Bot-Api-Secret-Token header. Leave empty to disable.
    TELEGRAM_WEBHOOK_SECRET: Optional[str] = None

    # Broadcast worker
    BROADCAST_BATCH_SIZE: int = 25
    BROADCAST_SEND_INTERVAL_MS: int = 75
    BROADCAST_MAX_ATTEMPTS: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
