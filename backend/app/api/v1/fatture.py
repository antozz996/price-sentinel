"""
Price Sentinel — Fatture Router.
Read-only con filtri per location/fornitore/tipo + marker management.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.fatture import Fattura, RigaFattura, MarkerFattura
from app.models.fornitori import Fornitore
from app.models.location import Location
from app.models.anomalie import Anomalia
from app.models.utenti import Utente
from app.schemas.fatture import FatturaResponse, RigaFatturaResponse

router = APIRouter()


@router.get(
    "/",
    summary="Lista fatture con filtri avanzati",
)
async def list_fatture(
    response: Response,
    location_id: int | None = Query(None),
    fornitore_id: int | None = Query(None),
    tipo_documento: str | None = Query(None),
    marker: str | None = Query(None),
    data_da: date | None = Query(None),
    data_a: date | None = Query(None),
    search: str | None = Query(None, description="Cerca per numero documento o descrizione prodotto"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Base query with joins for names
    query = (
        select(
            Fattura.id,
            Fattura.numero_documento,
            Fattura.data_documento,
            Fattura.data_ricezione_sdi,
            Fattura.tipo_documento,
            Fattura.totale_imponibile,
            Fattura.marker,
            Fattura.fornitore_id,
            Fattura.location_id,
            Fornitore.nome_azienda.label("fornitore_nome"),
            Location.nome_struttura.label("location_nome"),
            func.count(func.distinct(RigaFattura.id)).label("n_righe"),
            func.count(func.distinct(Anomalia.id)).label("n_anomalie"),
        )
        .outerjoin(Fornitore, Fattura.fornitore_id == Fornitore.id)
        .outerjoin(Location, Fattura.location_id == Location.id)
        .outerjoin(RigaFattura, RigaFattura.fattura_id == Fattura.id)
        .outerjoin(Anomalia, Anomalia.riga_fattura_id == RigaFattura.id)
        .group_by(
            Fattura.id, Fornitore.nome_azienda, Location.nome_struttura
        )
        .order_by(Fattura.data_documento.desc())
    )

    # Manager vede solo la propria location
    if current_user.ruolo.value == "manager" and current_user.location_id:
        query = query.where(Fattura.location_id == current_user.location_id)
    elif location_id:
        query = query.where(Fattura.location_id == location_id)

    if fornitore_id:
        query = query.where(Fattura.fornitore_id == fornitore_id)
    if tipo_documento:
        query = query.where(Fattura.tipo_documento == tipo_documento)
    if marker:
        query = query.where(Fattura.marker == marker)
    if data_da:
        query = query.where(Fattura.data_documento >= data_da)
    if data_a:
        query = query.where(Fattura.data_documento <= data_a)
    if search:
        query = query.where(
            Fattura.numero_documento.ilike(f"%{search}%")
        )

    # Count total from the subquery of the filtered base query
    count_query = select(func.count()).select_from(query.subquery())
    total_res = await db.execute(count_query)
    total = total_res.scalar() or 0
    response.headers["X-Total-Count"] = str(total)

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "id": r.id,
            "numero_documento": r.numero_documento,
            "data_documento": r.data_documento.isoformat(),
            "data_ricezione_sdi": r.data_ricezione_sdi.isoformat(),
            "tipo_documento": r.tipo_documento.value if hasattr(r.tipo_documento, 'value') else r.tipo_documento,
            "totale_imponibile": float(r.totale_imponibile),
            "marker": r.marker.value if hasattr(r.marker, 'value') else r.marker,
            "fornitore_id": r.fornitore_id,
            "location_id": r.location_id,
            "fornitore_nome": r.fornitore_nome or "Sconosciuto",
            "location_nome": r.location_nome or "N/D",
            "n_righe": r.n_righe,
            "n_anomalie": r.n_anomalie,
        }
        for r in rows
    ]


@router.patch(
    "/{fattura_id}/marker",
    summary="Aggiorna marker fattura",
)
async def update_marker(
    fattura_id: int,
    marker: str = Query(..., description="Nuovo marker"),
    current_user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Valida marker
    try:
        new_marker = MarkerFattura(marker)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Marker non valido. Valori ammessi: {[m.value for m in MarkerFattura]}"
        )

    result = await db.execute(select(Fattura).where(Fattura.id == fattura_id))
    fattura = result.scalar_one_or_none()
    if not fattura:
        raise HTTPException(status_code=404, detail="Fattura non trovata")

    fattura.marker = new_marker
    await db.flush()
    await db.refresh(fattura)

    return {"id": fattura.id, "marker": fattura.marker.value}


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
        raise HTTPException(status_code=404, detail="Fattura non trovata")

    result = await db.execute(
        select(RigaFattura)
        .where(RigaFattura.fattura_id == fattura_id)
        .order_by(RigaFattura.numero_linea)
    )
    return result.scalars().all()
