"""Venue readiness and explicit reconciliation configuration."""

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.database import get_db
from app.models.disputes import DisputeCase
from app.models.fatture import Fattura
from app.models.fornitori import Fornitore
from app.models.listino import ListinoMaster
from app.models.location import Location
from app.models.liquidstock_integration import LiquidStockSupplierOrder
from app.models.onboarding import LocationReconciliationSettings
from app.models.products import Product, SupplierProductAlias
from app.models.purchase_order_reconciliation import (
    LiquidStockVenueMapping,
    PurchaseOrderReconciliation,
)
from app.models.utenti import Utente
from app.schemas.onboarding import (
    LocationSettingsInput,
    LocationSettingsOut,
    OnboardingReadinessOut,
)


router = APIRouter()


DEFAULTS = {
    "price_tolerance_absolute": Decimal("0.01"),
    "price_tolerance_percent": Decimal("1"),
    "important_anomaly_threshold": Decimal("50"),
    "stalled_reconciliation_days": 3,
    "missing_credit_note_days": 7,
    "notifications_enabled": True,
}


def authorize_location(user: Utente, location_id: int) -> None:
    if user.ruolo.value != "admin" and user.location_id != location_id:
        raise HTTPException(status_code=403, detail="location_forbidden")


def settings_out(
    location_id: int,
    row: LocationReconciliationSettings | None,
) -> LocationSettingsOut:
    values = {
        key: getattr(row, key) if row else value
        for key, value in DEFAULTS.items()
    }
    return LocationSettingsOut(
        location_id=location_id,
        configured=row is not None,
        **values,
    )


@router.get(
    "/locations/{location_id}/readiness",
    response_model=OnboardingReadinessOut,
)
async def readiness(
    location_id: int,
    user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    authorize_location(user, location_id)
    location = await db.get(Location, location_id)
    if not location:
        raise HTTPException(status_code=404, detail="location_not_found")
    mapping = await db.scalar(
        select(LiquidStockVenueMapping).where(
            LiquidStockVenueMapping.location_id == location_id
        )
    )
    settings = await db.get(LocationReconciliationSettings, location_id)

    async def count(statement) -> int:
        return int(await db.scalar(statement) or 0)

    users = await count(
        select(func.count(Utente.id)).where(
            Utente.location_id == location_id, Utente.attivo.is_(True)
        )
    )
    suppliers = await count(
        select(func.count(Fornitore.id)).where(
            Fornitore.attivo_whitelist.is_(True)
        )
    )
    suppliers_with_contact = await count(
        select(func.count(Fornitore.id)).where(
            Fornitore.attivo_whitelist.is_(True),
            Fornitore.email_contatto.is_not(None),
        )
    )
    active_products = await count(
        select(func.count(Product.id)).where(Product.is_active.is_(True))
    )
    approved_aliases = await count(
        select(func.count(SupplierProductAlias.id)).where(
            SupplierProductAlias.status == "approved"
        )
    )
    price_lists = await count(select(func.count(ListinoMaster.id)))
    invoices = await count(
        select(func.count(Fattura.id)).where(Fattura.location_id == location_id)
    )
    disputes = await count(
        select(func.count(DisputeCase.id)).where(
            DisputeCase.location_id == location_id
        )
    )
    orders = 0
    reconciliations = 0
    if mapping:
        orders = await count(
            select(func.count(LiquidStockSupplierOrder.id)).where(
                LiquidStockSupplierOrder.liquidstock_venue_id
                == mapping.liquidstock_venue_id
            )
        )
        reconciliations = await count(
            select(func.count(PurchaseOrderReconciliation.id)).where(
                PurchaseOrderReconciliation.venue_id
                == mapping.liquidstock_venue_id
            )
        )
    return OnboardingReadinessOut(
        location_id=location_id,
        location_name=location.nome_struttura,
        users=users,
        suppliers=suppliers,
        suppliers_with_contact=suppliers_with_contact,
        active_products=active_products,
        approved_aliases=approved_aliases,
        price_lists=price_lists,
        liquidstock_venue_mapped=mapping is not None,
        liquidstock_orders=orders,
        invoices=invoices,
        reconciliations=reconciliations,
        disputes=disputes,
        settings_configured=settings is not None,
        settings=settings_out(location_id, settings),
    )


@router.get(
    "/locations/{location_id}/settings",
    response_model=LocationSettingsOut,
)
async def get_settings(
    location_id: int,
    user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    authorize_location(user, location_id)
    if not await db.get(Location, location_id):
        raise HTTPException(status_code=404, detail="location_not_found")
    return settings_out(
        location_id,
        await db.get(LocationReconciliationSettings, location_id),
    )


@router.put(
    "/locations/{location_id}/settings",
    response_model=LocationSettingsOut,
)
async def save_settings(
    location_id: int,
    payload: LocationSettingsInput,
    actor: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not await db.get(Location, location_id):
        raise HTTPException(status_code=404, detail="location_not_found")
    now = datetime.now(timezone.utc)
    row = await db.get(
        LocationReconciliationSettings, location_id, with_for_update=True
    )
    if row is None:
        row = LocationReconciliationSettings(
            location_id=location_id,
            created_by=actor.id,
            created_at=now,
        )
        db.add(row)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    row.updated_by = actor.id
    row.updated_at = now
    await db.flush()
    return settings_out(location_id, row)
