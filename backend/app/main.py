"""
Price Sentinel — FastAPI Application Factory.
Sistema di Audit Automatizzato degli Acquisti.
"""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import settings
from app.database import async_session_factory
from app.services.automation import run_operational_monitor


logger = logging.getLogger("price_sentinel.automation")


async def _automation_loop() -> None:
    while True:
        try:
            async with async_session_factory() as session:
                async with session.begin():
                    await run_operational_monitor(session)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("operational_monitor_failed")
        await asyncio.sleep(settings.AUTOMATION_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup e shutdown hooks."""
    # Startup: importa i modelli per registrare metadata
    import app.models  # noqa: F401
    automation_task = (
        asyncio.create_task(_automation_loop())
        if settings.AUTOMATION_ENABLED
        else None
    )
    yield
    if automation_task:
        automation_task.cancel()
        with suppress(asyncio.CancelledError):
            await automation_task


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
        redirect_slashes=False,
    )

    # ── Trailing Slash Middleware ─────────────
    class TrailingSlashMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                path = scope["path"]
                base_routes = {
                    "/api/v1/location",
                    "/api/v1/fornitori",
                    "/api/v1/listino",
                    "/api/v1/fatture",
                    "/api/v1/anomalie",
                    "/api/v1/alias",
                    "/api/v1/utenti",
                    "/api/v1/webhook",
                    "/api/v1/ingestion",
                    "/api/v1/intelligence",
                    "/api/v1/accordi",
                    "/api/v1/ordini",
                    "/api/v1/sku",
                    "/api/v1/ai",
                }
                if path in base_routes:
                    scope["path"] = path + "/"
            await self.app(scope, receive, send)

    application.add_middleware(TrailingSlashMiddleware)

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
