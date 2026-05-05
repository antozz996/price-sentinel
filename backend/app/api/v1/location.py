"""
Price Sentinel — Location Router.
CRUD Location — Admin per scrittura, tutti per lettura.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.database import get_db
from app.models.location import Location, TipologiaLocation
from app.models.utenti import Utente
from app.schemas.location import LocationCreate, LocationResponse, LocationUpdate

router = APIRouter()


@router.get(
    "/",
    response_model=list[LocationResponse],
    summary="Lista location",
)
async def list_location(
    _user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Location).order_by(Location.nome_struttura))
    return result.scalars().all()


@router.post(
    "/",
    response_model=LocationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crea location",
)
async def create_location(
    data: LocationCreate,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    # Verifica P.IVA unica
    existing = await db.execute(
        select(Location).where(Location.piva_riferimento == data.piva_riferimento)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="P.IVA già registrata")

    location = Location(
        nome_struttura=data.nome_struttura,
        piva_riferimento=data.piva_riferimento,
        tipologia=TipologiaLocation(data.tipologia),
    )
    db.add(location)
    await db.flush()
    await db.refresh(location)
    return location


@router.get(
    "/{location_id}",
    response_model=LocationResponse,
    summary="Dettaglio location",
)
async def get_location(
    location_id: int,
    _user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Location).where(Location.id == location_id))
    location = result.scalar_one_or_none()
    if not location:
        raise HTTPException(status_code=404, detail="Location non trovata")
    return location


@router.patch(
    "/{location_id}",
    response_model=LocationResponse,
    summary="Aggiorna location",
)
async def update_location(
    location_id: int,
    data: LocationUpdate,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Location).where(Location.id == location_id))
    location = result.scalar_one_or_none()
    if not location:
        raise HTTPException(status_code=404, detail="Location non trovata")

    update_data = data.model_dump(exclude_unset=True)
    if "tipologia" in update_data:
        location.tipologia = TipologiaLocation(update_data.pop("tipologia"))
    for key, value in update_data.items():
        setattr(location, key, value)

    await db.flush()
    await db.refresh(location)
    return location
