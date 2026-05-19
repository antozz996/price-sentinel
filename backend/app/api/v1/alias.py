"""
Price Sentinel — Alias Prodotti Router.
CRUD alias codice fornitore → SKU interno — Spec §3.1 Livello 1.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.alias import AliasProdotto
from app.models.utenti import Utente
from app.schemas.alias import AliasCreate, AliasResponse

router = APIRouter()


@router.get(
    "/",
    response_model=list[AliasResponse],
    summary="Lista alias prodotti",
)
async def list_alias(
    fornitore_id: int | None = Query(None),
    _user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(AliasProdotto).order_by(AliasProdotto.created_at.desc())
    if fornitore_id:
        query = query.where(AliasProdotto.fornitore_id == fornitore_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.post(
    "/",
    response_model=AliasResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crea alias prodotto",
    description="Conferma mappatura codice fornitore → SKU interno. Salvato permanentemente.",
)
async def create_alias(
    data: AliasCreate,
    current_user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verifica duplicato
    existing = await db.execute(
        select(AliasProdotto).where(
            AliasProdotto.fornitore_id == data.fornitore_id,
            AliasProdotto.codice_fornitore_originale == data.codice_fornitore_originale,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="Alias già esistente per questo codice fornitore",
        )

    alias = AliasProdotto(
        fornitore_id=data.fornitore_id,
        codice_fornitore_originale=data.codice_fornitore_originale,
        sku_interno=data.sku_interno,
        coefficiente_conversione=data.coefficiente_conversione,
        confermato_da_user_id=current_user.id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(alias)
    await db.flush()
    await db.refresh(alias)
    return alias


@router.delete(
    "/{alias_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Elimina alias",
)
async def delete_alias(
    alias_id: int,
    _user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AliasProdotto).where(AliasProdotto.id == alias_id))
    alias = result.scalar_one_or_none()
    if not alias:
        raise HTTPException(status_code=404, detail="Alias non trovato")

    await db.delete(alias)
    await db.flush()
