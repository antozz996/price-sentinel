"""
Price Sentinel — Fatture Router.
Read-only con filtri per location/fornitore/tipo.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.fatture import Fattura, RigaFattura
from app.models.anomalie import Anomalia
from app.models.utenti import Utente
from app.schemas.fatture import FatturaResponse, RigaFatturaResponse

router = APIRouter()


@router.get(
    "/",
    response_model=list[FatturaResponse],
    summary="Lista fatture",
)
async def list_fatture(
    location_id: int | None = Query(None),
    fornitore_id: int | None = Query(None),
    tipo_documento: str | None = Query(None),
    data_da: date | None = Query(None),
    data_a: date | None = Query(None),
    current_user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Fattura).order_by(Fattura.data_documento.desc())

    # Manager vede solo la propria location — Spec §6.2
    if current_user.ruolo.value == "manager" and current_user.location_id:
        query = query.where(Fattura.location_id == current_user.location_id)
    elif location_id:
        query = query.where(Fattura.location_id == location_id)

    if fornitore_id:
        query = query.where(Fattura.fornitore_id == fornitore_id)
    if tipo_documento:
        query = query.where(Fattura.tipo_documento == tipo_documento)
    if data_da:
        query = query.where(Fattura.data_documento >= data_da)
    if data_a:
        query = query.where(Fattura.data_documento <= data_a)

    result = await db.execute(query)
    return result.scalars().all()


@router.get(
    "/{fattura_id}",
    response_model=FatturaResponse,
    summary="Dettaglio fattura",
)
async def get_fattura(
    fattura_id: int,
    current_user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Fattura).where(Fattura.id == fattura_id)

    # Manager vede solo la propria location
    if current_user.ruolo.value == "manager" and current_user.location_id:
        query = query.where(Fattura.location_id == current_user.location_id)

    result = await db.execute(query)
    fattura = result.scalar_one_or_none()
    if not fattura:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Fattura non trovata")
    return fattura


@router.get(
    "/{fattura_id}/righe",
    response_model=list[RigaFatturaResponse],
    summary="Righe fattura",
)
async def list_righe_fattura(
    fattura_id: int,
    current_user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verifica accesso alla fattura
    fattura_query = select(Fattura).where(Fattura.id == fattura_id)
    if current_user.ruolo.value == "manager" and current_user.location_id:
        fattura_query = fattura_query.where(
            Fattura.location_id == current_user.location_id
        )
    fattura_result = await db.execute(fattura_query)
    if not fattura_result.scalar_one_or_none():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Fattura non trovata")

    result = await db.execute(
        select(RigaFattura)
        .where(RigaFattura.fattura_id == fattura_id)
        .order_by(RigaFattura.numero_linea)
    )
    return result.scalars().all()
