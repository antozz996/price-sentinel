"""
Price Sentinel — Location Router.
CRUD Location — Admin per scrittura, tutti per lettura.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
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
    summary="Lista tutte le location",
)
async def list_locations(
    current_user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Location).order_by(Location.nome_struttura)
    result = await db.execute(query)
    return result.scalars().all()


@router.post(
    "/",
    response_model=LocationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crea nuova location",
)
async def create_location(
    payload: LocationCreate,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    # Verifica P.IVA duplicata
    query = select(Location).where(Location.piva_riferimento == payload.piva_riferimento)
    existing = (await db.execute(query)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=400, detail="Location con questa P.IVA già presente"
        )

    loc = Location(
        nome_struttura=payload.nome_struttura,
        piva_riferimento=payload.piva_riferimento,
        tipologia=payload.tipologia,
    )
    db.add(loc)
    await db.commit()
    await db.refresh(loc)
    return loc


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


@router.put(
    "/{location_id}",
    response_model=LocationResponse,
    summary="Aggiorna location",
)
async def update_location(
    location_id: int,
    payload: LocationUpdate,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    query = select(Location).where(Location.id == location_id)
    loc = (await db.execute(query)).scalar_one_or_none()
    if not loc:
        raise HTTPException(status_code=404, detail="Location non trovata")

    if payload.piva_riferimento is not None:
        # Verifica duplicati
        dup_query = select(Location).where(
            Location.piva_riferimento == payload.piva_riferimento,
            Location.id != location_id,
        )
        dup = (await db.execute(dup_query)).scalar_one_or_none()
        if dup:
            raise HTTPException(
                status_code=400,
                detail="P.IVA già associata ad un'altra location",
            )
        loc.piva_riferimento = payload.piva_riferimento

    if payload.nome_struttura is not None:
        loc.nome_struttura = payload.nome_struttura
    if payload.tipologia is not None:
        loc.tipologia = payload.tipologia

    await db.commit()
    await db.refresh(loc)
    return loc


@router.delete(
    "/{location_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Elimina location",
)
async def delete_location(
    location_id: int,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Location).where(Location.id == location_id))
    location = result.scalar_one_or_none()
    if not location:
        raise HTTPException(status_code=404, detail="Location non trovata")
    
    try:
        # 1. Note di credito
        await db.execute(
            text("""
                DELETE FROM note_di_credito 
                WHERE anomalia_id IN (
                    SELECT a.id FROM anomalie a 
                    JOIN righe_fattura r ON r.id = a.riga_fattura_id
                    JOIN fatture f ON f.id = r.fattura_id
                    WHERE f.location_id = :location_id
                )
            """),
            {"location_id": location_id}
        )
        
        # 2. Anomalie
        await db.execute(
            text("""
                DELETE FROM anomalie 
                WHERE riga_fattura_id IN (
                    SELECT r.id FROM righe_fattura r
                    JOIN fatture f ON f.id = r.fattura_id
                    WHERE f.location_id = :location_id
                )
            """),
            {"location_id": location_id}
        )

        
        # 4. Righe fattura
        await db.execute(
            text("""
                DELETE FROM righe_fattura 
                WHERE fattura_id IN (
                    SELECT id FROM fatture 
                    WHERE location_id = :location_id
                )
            """),
            {"location_id": location_id}
        )
        
        # 5. Fatture
        await db.execute(
            text("DELETE FROM fatture WHERE location_id = :location_id"),
            {"location_id": location_id}
        )
        
        # 6. Upload batches
        await db.execute(
            text("DELETE FROM upload_batches WHERE location_id = :location_id"),
            {"location_id": location_id}
        )
        
        # 7. Righe ordine
        await db.execute(
            text("""
                DELETE FROM righe_ordine
                WHERE ordine_id IN (
                    SELECT id FROM ordini
                    WHERE location_id = :location_id
                )
            """),
            {"location_id": location_id}
        )
        
        # 8. Ordini
        await db.execute(
            text("DELETE FROM ordini WHERE location_id = :location_id"),
            {"location_id": location_id}
        )
        
        # 9. Update utenti (set location_id to NULL)
        await db.execute(
            text("UPDATE utenti SET location_id = NULL WHERE location_id = :location_id"),
            {"location_id": location_id}
        )
        
        # 10. Location
        await db.execute(
            text("DELETE FROM location WHERE id = :location_id"),
            {"location_id": location_id}
        )
        
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Impossibile eliminare la location a causa di un errore di database: {str(e)}"
        )
