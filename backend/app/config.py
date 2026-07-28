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
    DATABASE_URL_ENV: str = Field(alias="DATABASE_URL", min_length=1)

    @property
    def database_url(self) -> str:
        """Stringa di connessione asyncpg per SQLAlchemy."""
        return self.DATABASE_URL_ENV

    @property
    def database_url_sync(self) -> str:
        """Stringa di connessione sincrona per Alembic."""
        return self.DATABASE_URL_ENV.replace("asyncpg", "psycopg2")

    # ── Auth / JWT ───────────────────────────
    SECRET_KEY: str = Field(min_length=32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30  # 30 minuti

    # ── Aruba Webhook ────────────────────────
    ARUBA_WEBHOOK_API_KEY: str = Field(min_length=1)

    # ── LiquidStock server-to-server bridge ──
    LIQUIDSTOCK_INTEGRATION_SECRET: str = Field(min_length=32)
    LIQUIDSTOCK_INTEGRATION_PREVIOUS_SECRET: str = ""
    INTEGRATION_MAX_CLOCK_SKEW_SECONDS: int = 300

    # ── Notifiche (Sprint 3) ─────────────────
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ADMIN_CHAT_ID: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""

    # ── Safe operational monitor ─────────────
    AUTOMATION_ENABLED: bool = False
    AUTOMATION_INTERVAL_SECONDS: int = Field(default=900, ge=60, le=86400)

    # ── Ambiente ─────────────────────────────
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

settings = Settings()
