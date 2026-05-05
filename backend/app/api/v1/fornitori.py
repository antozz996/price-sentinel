"""
Price Sentinel — Fornitori Router.
CRUD Fornitori con toggle whitelist — Admin only.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
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
