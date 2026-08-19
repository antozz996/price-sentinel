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
    stmt = select(Utente).order_by(Utente.id)
    if getattr(_admin, "tenant_id", None):
        stmt = stmt.where(Utente.tenant_id == _admin.tenant_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post(
    "/",
    response_model=UtenteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crea utente/operatore",
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

    base_ruolo = RuoloUtente.admin if data.ruolo == "admin" or data.ruolo_dettagliato == "admin" else RuoloUtente.manager

    utente = Utente(
        email=data.email,
        password_hash=hash_password(data.password),
        ruolo=base_ruolo,
        ruolo_dettagliato=data.ruolo_dettagliato or ("admin" if data.ruolo == "admin" else "manager_sede"),
        settore_abilitato=data.settore_abilitato or "all",
        nome_completo=data.nome_completo,
        location_id=data.location_id,
        tenant_id=getattr(_admin, "tenant_id", 1) or 1,
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
    summary="Aggiorna utente/operatore",
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

    if "password" in update_data and update_data["password"]:
        utente.password_hash = hash_password(update_data.pop("password"))
    elif "password" in update_data:
        update_data.pop("password")

    if "ruolo_dettagliato" in update_data:
        det = update_data["ruolo_dettagliato"]
        utente.ruolo = RuoloUtente.admin if det == "admin" else RuoloUtente.manager

    if "ruolo" in update_data:
        r = update_data.pop("ruolo")
        utente.ruolo = RuoloUtente.admin if r == "admin" else RuoloUtente.manager

    for key, value in update_data.items():
        setattr(utente, key, value)

    await db.flush()
    await db.refresh(utente)
    return utente


@router.delete(
    "/{utente_id}",
    summary="Elimina o disattiva utente",
)
async def delete_utente(
    utente_id: int,
    _admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if utente_id == _admin.id:
        raise HTTPException(status_code=400, detail="Non puoi eliminare il tuo stesso account amministratore")

    result = await db.execute(select(Utente).where(Utente.id == utente_id))
    utente = result.scalar_one_or_none()
    if not utente:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    try:
        await db.delete(utente)
        await db.flush()
    except Exception:
        # Se ha chiavi esterne, disattiva logicamente
        await db.rollback()
        res2 = await db.execute(select(Utente).where(Utente.id == utente_id))
        u2 = res2.scalar_one()
        u2.attivo = False
        await db.flush()

    return {"status": "success", "message": "Utente eliminato/disattivato con successo"}
