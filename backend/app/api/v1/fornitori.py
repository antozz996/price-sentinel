"""
Price Sentinel — Fornitori Router.
CRUD Fornitori con toggle whitelist — Admin only.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.database import get_db
from app.models.fornitori import Fornitore
from app.models.utenti import Utente
from app.schemas.fornitori import FornitoreCreate, FornitoreResponse, FornitoreUpdate

router = APIRouter()


@router.get(
    "/",
    response_model=list[FornitoreResponse],
    summary="Lista fornitori",
)
async def list_fornitori(
    attivi: bool | None = None,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    query = select(Fornitore).order_by(Fornitore.nome_azienda)
    if attivi is not None:
        query = query.where(Fornitore.attivo_whitelist == attivi)
    result = await db.execute(query)
    return result.scalars().all()


@router.post(
    "/",
    response_model=FornitoreResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crea fornitore",
)
async def create_fornitore(
    data: FornitoreCreate,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(Fornitore).where(Fornitore.partita_iva == data.partita_iva)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="P.IVA fornitore già registrata")

    fornitore = Fornitore(
        partita_iva=data.partita_iva,
        nome_azienda=data.nome_azienda,
        attivo_whitelist=data.attivo_whitelist,
        email_contatto=data.email_contatto,
    )
    db.add(fornitore)
    await db.flush()
    await db.refresh(fornitore)
    return fornitore


@router.get(
    "/{fornitore_id}",
    response_model=FornitoreResponse,
    summary="Dettaglio fornitore",
)
async def get_fornitore(
    fornitore_id: int,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Fornitore).where(Fornitore.id == fornitore_id))
    fornitore = result.scalar_one_or_none()
    if not fornitore:
        raise HTTPException(status_code=404, detail="Fornitore non trovato")
    return fornitore


@router.patch(
    "/{fornitore_id}",
    response_model=FornitoreResponse,
    summary="Aggiorna fornitore",
)
async def update_fornitore(
    fornitore_id: int,
    data: FornitoreUpdate,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Fornitore).where(Fornitore.id == fornitore_id))
    fornitore = result.scalar_one_or_none()
    if not fornitore:
        raise HTTPException(status_code=404, detail="Fornitore non trovato")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(fornitore, key, value)

    await db.flush()
    await db.refresh(fornitore)
    return fornitore


@router.patch(
    "/{fornitore_id}/whitelist",
    response_model=FornitoreResponse,
    summary="Toggle whitelist fornitore",
)
async def toggle_whitelist(
    fornitore_id: int,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Inverte lo stato della whitelist — attiva/disattiva matching."""
    result = await db.execute(select(Fornitore).where(Fornitore.id == fornitore_id))
    fornitore = result.scalar_one_or_none()
    if not fornitore:
        raise HTTPException(status_code=404, detail="Fornitore non trovato")

    fornitore.attivo_whitelist = not fornitore.attivo_whitelist
    await db.flush()
    await db.refresh(fornitore)
    return fornitore


@router.delete(
    "/{fornitore_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Elimina fornitore",
)
async def delete_fornitore(
    fornitore_id: int,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Fornitore).where(Fornitore.id == fornitore_id))
    fornitore = result.scalar_one_or_none()
    if not fornitore:
        raise HTTPException(status_code=404, detail="Fornitore non trovato")
    
    try:
        # 1. Note di credito
        await db.execute(
            text("""
                DELETE FROM note_di_credito 
                WHERE anomalia_id IN (
                    SELECT a.id FROM anomalie a 
                    JOIN righe_fattura r ON r.id = a.riga_fattura_id
                    JOIN fatture f ON f.id = r.fattura_id
                    WHERE f.fornitore_id = :fornitore_id
                )
            """),
            {"fornitore_id": fornitore_id}
        )
        
        # 2. Anomalie
        await db.execute(
            text("""
                DELETE FROM anomalie 
                WHERE riga_fattura_id IN (
                    SELECT r.id FROM righe_fattura r
                    JOIN fatture f ON f.id = r.fattura_id
                    WHERE f.fornitore_id = :fornitore_id
                )
            """),
            {"fornitore_id": fornitore_id}
        )

        
        # 4. Righe fattura
        await db.execute(
            text("""
                DELETE FROM righe_fattura 
                WHERE fattura_id IN (
                    SELECT id FROM fatture 
                    WHERE fornitore_id = :fornitore_id
                )
            """),
            {"fornitore_id": fornitore_id}
        )
        
        # 5. Fatture
        await db.execute(
            text("DELETE FROM fatture WHERE fornitore_id = :fornitore_id"),
            {"fornitore_id": fornitore_id}
        )
        
        # 6. Righe ordine (listino)
        await db.execute(
            text("""
                DELETE FROM righe_ordine
                WHERE listino_id IN (
                    SELECT id FROM listino_master
                    WHERE fornitore_id = :fornitore_id
                )
            """),
            {"fornitore_id": fornitore_id}
        )
        
        # 7. UOM conversioni
        await db.execute(
            text("""
                DELETE FROM uom_conversioni
                WHERE listino_id IN (
                    SELECT id FROM listino_master
                    WHERE fornitore_id = :fornitore_id
                )
            """),
            {"fornitore_id": fornitore_id}
        )
        
        # 8. PFA scaglioni
        await db.execute(
            text("""
                DELETE FROM pfa_scaglioni
                WHERE listino_id IN (
                    SELECT id FROM listino_master
                    WHERE fornitore_id = :fornitore_id
                )
            """),
            {"fornitore_id": fornitore_id}
        )
        
        # 9. Listino master
        await db.execute(
            text("DELETE FROM listino_master WHERE fornitore_id = :fornitore_id"),
            {"fornitore_id": fornitore_id}
        )
        
        # 10. Righe ordine (ordine)
        await db.execute(
            text("""
                DELETE FROM righe_ordine
                WHERE ordine_id IN (
                    SELECT id FROM ordini
                    WHERE fornitore_id = :fornitore_id
                )
            """),
            {"fornitore_id": fornitore_id}
        )
        
        # 11. Ordini
        await db.execute(
            text("DELETE FROM ordini WHERE fornitore_id = :fornitore_id"),
            {"fornitore_id": fornitore_id}
        )
        
        # 12. Alias prodotti
        await db.execute(
            text("DELETE FROM alias_prodotti WHERE fornitore_id = :fornitore_id"),
            {"fornitore_id": fornitore_id}
        )
        
        # 13. Fornitore
        await db.execute(
            text("DELETE FROM fornitori WHERE id = :fornitore_id"),
            {"fornitore_id": fornitore_id}
        )
        
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Impossibile eliminare il fornitore a causa di un errore di database: {str(e)}"
        )
