"""
Price Sentinel — Database engine e session factory.
Usa AsyncSession con asyncpg per performance.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


# ── Engine ───────────────────────────────────
engine = create_async_engine(
    settings.database_url,
    echo=settings.DEBUG,
    pool_size=10,
    # Per worker: production runs 3 uvicorn workers, 3 x 20 stays well under max_connections=100.
    max_overflow=10,
    pool_pre_ping=True,
)

# ── Session Factory ──────────────────────────
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ── Base Declarativa ─────────────────────────
class Base(DeclarativeBase):
    """Base class per tutti i modelli SQLAlchemy."""
    pass


# ── Dependency Injection ─────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield una sessione DB per ogni request FastAPI."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
