"""
Price Sentinel — Utenti Router.
CRUD utenti — solo Admin.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.database import get_db
from app.models.utenti import Utente, RuoloUtente
from app.schemas.utenti import UtenteCreate, UtenteResponse, UtenteUpdate
from app.services.auth import hash_password

router = APIRouter()


@router.get(
    "/",
    response_model=list[UtenteResponse],
    summary="Lista utenti",
)
async def list_utenti(
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Utente).order_by(Utente.id))
    return result.scalars().all()


@router.post(
    "/",
    response_model=UtenteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crea utente",
)
async def create_utente(
    data: UtenteCreate,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    # Verifica email unica
    existing = await db.execute(select(Utente).where(Utente.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email già registrata")

    utente = Utente(
        email=data.email,
        password_hash=hash_password(data.password),
        ruolo=RuoloUtente(data.ruolo),
        location_id=data.location_id,
        attivo=data.attivo,
    )
    db.add(utente)
    await db.flush()
    await db.refresh(utente)
    return utente


@router.get(
    "/{utente_id}",
    response_model=UtenteResponse,
    summary="Dettaglio utente",
)
async def get_utente(
    utente_id: int,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Utente).where(Utente.id == utente_id))
    utente = result.scalar_one_or_none()
    if not utente:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    return utente


@router.patch(
    "/{utente_id}",
    response_model=UtenteResponse,
    summary="Aggiorna utente",
)
async def update_utente(
    utente_id: int,
    data: UtenteUpdate,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Utente).where(Utente.id == utente_id))
    utente = result.scalar_one_or_none()
    if not utente:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    update_data = data.model_dump(exclude_unset=True)

    if "password" in update_data:
        utente.password_hash = hash_password(update_data.pop("password"))
    if "ruolo" in update_data:
        utente.ruolo = RuoloUtente(update_data.pop("ruolo"))

    for key, value in update_data.items():
        setattr(utente, key, value)

    await db.flush()
    await db.refresh(utente)
    return utente
