"""
Price Sentinel — Router Aggregator v1.
Monta tutti i sub-router sotto /api/v1.
"""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1 import (
    alias,
    anomalie,
    auth,
    fatture,
    fornitori,
    intelligence,
    listino,
    location,
    utenti,
    webhook,
    ingestion,
    ordini,
    sku_manager,
    ai,
    accordi,
)

api_router = APIRouter(redirect_slashes=False)

api_router.include_router(auth.router, prefix="/auth", tags=["Autenticazione"])
api_router.include_router(utenti.router, prefix="/utenti", tags=["Utenti"])
api_router.include_router(location.router, prefix="/location", tags=["Location"])
api_router.include_router(fornitori.router, prefix="/fornitori", tags=["Fornitori"])
api_router.include_router(listino.router, prefix="/listino", tags=["Listino Master"])
api_router.include_router(fatture.router, prefix="/fatture", tags=["Fatture (API private)"])
api_router.include_router(anomalie.router, prefix="/anomalie", tags=["Anomalie Workflow"])
api_router.include_router(alias.router, prefix="/alias", tags=["Alias Prodotti"])
api_router.include_router(webhook.router, prefix="/webhook", tags=["Webhook Ingestion"])
api_router.include_router(ingestion.router, prefix="/ingestion", tags=["Ingestion Manuale"])
api_router.include_router(intelligence.router, prefix="/intelligence", tags=["Intelligence & Admin"])
api_router.include_router(ordini.router, prefix="/ordini", tags=["Ottimizzazione Ordini"])
api_router.include_router(sku_manager.router, prefix="/sku", tags=["Gestione SKU"])
api_router.include_router(ai.router, prefix="/ai", tags=["Sentinel AI"])
api_router.include_router(accordi.router, prefix="/accordi", tags=["Accordi Commerciali"])
