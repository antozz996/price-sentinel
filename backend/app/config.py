"""
Price Sentinel — Configurazione centralizzata.
Legge variabili d'ambiente dal file .env via pydantic-settings.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurazione globale dell'applicazione."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Database ─────────────────────────────
    POSTGRES_USER: str = "sentinel"
    POSTGRES_PASSWORD: str = "sentinel_dev_2025"
    POSTGRES_DB: str = "price_sentinel"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432
    DATABASE_URL_ENV: str | None = Field(default=None, alias="DATABASE_URL")

    @property
    def database_url(self) -> str:
        """Stringa di connessione asyncpg per SQLAlchemy."""
        if self.DATABASE_URL_ENV:
            return self.DATABASE_URL_ENV
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def database_url_sync(self) -> str:
        """Stringa di connessione sincrona per Alembic."""
        if self.DATABASE_URL_ENV:
            return self.DATABASE_URL_ENV.replace("asyncpg", "psycopg2")
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ── Auth / JWT ───────────────────────────
    SECRET_KEY: str = "fallback_secret_key_if_missing_in_vercel_123"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30  # 30 minuti

    # ── Aruba Webhook ────────────────────────
    ARUBA_WEBHOOK_API_KEY: str = ""

    # ── Notifiche (Sprint 3) ─────────────────
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ADMIN_CHAT_ID: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""

    # ── Ambiente ─────────────────────────────
    ENVIRONMENT: str = "development"
    DEBUG: bool = True


settings = Settings()
