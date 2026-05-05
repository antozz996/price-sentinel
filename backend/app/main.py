"""
Price Sentinel — FastAPI Application Factory.
Sistema di Audit Automatizzato degli Acquisti.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup e shutdown hooks."""
    # Startup: importa i modelli per registrare metadata
    import app.models  # noqa: F401
    yield
    # Shutdown: cleanup se necessario


def create_app() -> FastAPI:
    """Factory pattern per creare l'istanza FastAPI."""

    application = FastAPI(
        title="Price Sentinel",
        description=(
            "Sistema di Audit Automatizzato degli Acquisti — "
            "Holding Multi-Location Ho.Re.Ca."
        ),
        version="1.0.0",
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    # ── CORS ─────────────────────────────────
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.DEBUG else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ──────────────────────────────
    application.include_router(api_router, prefix="/api/v1")

    # ── Health Check ─────────────────────────
    @application.get(
        "/api/v1/health",
        tags=["System"],
        summary="Health check",
    )
    async def health():
        return {
            "status": "healthy",
            "service": "Price Sentinel",
            "version": "1.0.0",
            "environment": settings.ENVIRONMENT,
        }

    return application


# ── App instance per Uvicorn ─────────────────
app = create_app()
