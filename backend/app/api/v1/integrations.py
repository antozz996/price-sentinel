"""Dedicated inbound API for the LiquidStock bridge."""

import hashlib
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.fornitori import Fornitore
from app.models.liquidstock_integration import LiquidStockIntegrationEvent
from app.models.products import Product
from app.schemas.liquidstock_integration import (
    CatalogSearchRequest,
    IntegrationEventResponse,
    LiquidStockEventPayload,
    ProductCatalogItem,
    SupplierCatalogItem,
)
from app.services.liquidstock_auth import verify_liquidstock_request
from app.services.liquidstock_projection import (
    ProjectionError,
    apply_liquidstock_event,
)


router = APIRouter()


def _safe_event_metadata(payload: object) -> tuple[str, str, dict]:
    if not isinstance(payload, dict):
        return "invalid", "invalid", {"_invalid_payload": True}
    event_type = payload.get("event_type")
    version = payload.get("integration_version")
    safe_event_type = (
        event_type if isinstance(event_type, str) and len(event_type) <= 80 else "invalid"
    )
    safe_version = (
        version if isinstance(version, str) and len(version) <= 20 else "invalid"
    )
    return safe_event_type, safe_version, payload


@router.post(
    "/liquidstock/events",
    response_model=IntegrationEventResponse,
    summary="Receive a signed LiquidStock integration event",
)
async def receive_liquidstock_event(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    raw_body = await request.body()
    verified = verify_liquidstock_request(request, raw_body)
    payload_hash = hashlib.sha256(raw_body).hexdigest()
    try:
        raw_payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raw_payload = None
    event_type, integration_version, stored_payload = _safe_event_metadata(
        raw_payload
    )
    now = datetime.now(timezone.utc)

    insert_result = await db.execute(
        pg_insert(LiquidStockIntegrationEvent)
        .values(
            source="liquidstock",
            external_event_id=verified.event_id,
            event_type=event_type,
            integration_version=integration_version,
            payload=stored_payload,
            payload_hash=payload_hash,
            received_at=now,
            processing_status="received",
            created_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=["source", "external_event_id"]
        )
        .returning(LiquidStockIntegrationEvent.id)
    )
    created_id = insert_result.scalar_one_or_none()
    duplicate = created_id is None
    event = await db.scalar(
        select(LiquidStockIntegrationEvent)
        .where(
            LiquidStockIntegrationEvent.source == "liquidstock",
            LiquidStockIntegrationEvent.external_event_id == verified.event_id,
        )
        .with_for_update()
    )
    if event is None:
        return JSONResponse(
            status_code=503,
            content={"accepted": False, "error": "integration_unavailable"},
        )
    if event.payload_hash != payload_hash:
        return JSONResponse(
            status_code=409,
            content={
                "accepted": False,
                "event_id": str(verified.event_id),
                "error": "event_conflict",
            },
        )
    if duplicate and event.processing_status == "processed":
        return IntegrationEventResponse(
            accepted=True, event_id=verified.event_id, duplicate=True
        )

    try:
        payload = LiquidStockEventPayload.model_validate(raw_payload)
    except ValidationError:
        validation_code = "invalid_payload"
        if integration_version != "1.0":
            validation_code = "unsupported_integration_version"
        elif event_type not in {
            "supplier_order_confirmed",
            "supplier_order_received",
            "supplier_order_cancelled",
        }:
            validation_code = "unsupported_event_type"
        event.processing_status = "failed"
        event.processing_error = validation_code
        event.processed_at = None
        await db.flush()
        return JSONResponse(
            status_code=422,
            content={
                "accepted": False,
                "event_id": str(verified.event_id),
                "error": "event_rejected",
            },
        )

    try:
        async with db.begin_nested():
            await apply_liquidstock_event(db, event, payload)
    except ProjectionError as exc:
        event.processing_status = "failed"
        event.processing_error = exc.code
        event.processed_at = None
        await db.flush()
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "accepted": False,
                "event_id": str(verified.event_id),
                "error": "event_rejected",
            },
        )
    except Exception:
        event.processing_status = "failed"
        event.processing_error = "projection_failure"
        event.processed_at = None
        await db.flush()
        return JSONResponse(
            status_code=500,
            content={
                "accepted": False,
                "event_id": str(verified.event_id),
                "error": "event_processing_failed",
            },
        )

    event.processing_status = "processed"
    event.processing_error = None
    event.processed_at = datetime.now(timezone.utc)
    await db.flush()
    return IntegrationEventResponse(
        accepted=True,
        event_id=verified.event_id,
        duplicate=duplicate,
    )


async def _catalog_request(request: Request) -> CatalogSearchRequest:
    raw_body = await request.body()
    verify_liquidstock_request(request, raw_body)
    try:
        return CatalogSearchRequest.model_validate_json(raw_body)
    except ValidationError:
        raise ProjectionError("invalid_catalog_request", 422) from None


@router.post(
    "/liquidstock/catalog/suppliers/search",
    response_model=list[SupplierCatalogItem],
    summary="Search canonical Price Sentinel suppliers",
)
async def search_liquidstock_suppliers(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    try:
        search = await _catalog_request(request)
    except ProjectionError:
        return JSONResponse(
            status_code=422, content={"error": "catalog_request_rejected"}
        )
    statement = select(Fornitore)
    if search.id is not None:
        statement = statement.where(Fornitore.id == search.id)
    else:
        statement = statement.where(
            Fornitore.nome_azienda.ilike(f"%{search.query.strip()}%")
        )
    suppliers = (
        await db.scalars(statement.order_by(Fornitore.nome_azienda).limit(search.limit))
    ).all()
    return [
        SupplierCatalogItem(
            id=item.id,
            name=item.nome_azienda,
            vat_number=item.partita_iva,
            is_active=item.attivo_whitelist,
        )
        for item in suppliers
    ]


@router.post(
    "/liquidstock/catalog/products/search",
    response_model=list[ProductCatalogItem],
    summary="Search canonical Price Sentinel products",
)
async def search_liquidstock_products(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    try:
        search = await _catalog_request(request)
    except ProjectionError:
        return JSONResponse(
            status_code=422, content={"error": "catalog_request_rejected"}
        )
    statement = select(Product)
    if search.id is not None:
        statement = statement.where(Product.id == search.id)
    else:
        statement = statement.where(
            Product.canonical_name.ilike(f"%{search.query.strip()}%")
        )
    products = (
        await db.scalars(statement.order_by(Product.canonical_name).limit(search.limit))
    ).all()
    return [
        ProductCatalogItem(
            id=item.id,
            name=item.canonical_name,
            sku=item.sku_interno,
            category=item.category,
            is_active=item.is_active,
        )
        for item in products
    ]
