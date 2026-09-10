"""
Price Sentinel — Fornitori Router.
CRUD Fornitori con toggle whitelist — Admin only.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.api.deps import get_current_user, require_admin
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
    include_archived: bool = False,
    _user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Fornitore).options(noload("*")).order_by(Fornitore.nome_azienda)
    if not include_archived:
        query = query.where(Fornitore.archived_at.is_(None))
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
    clean_piva = data.partita_iva.strip().replace(" ", "").upper()
    clean_nome = data.nome_azienda.strip()

    # Search existing by exact clean_piva or with/without IT prefix
    piva_candidates = [clean_piva]
    if clean_piva.startswith("IT") and len(clean_piva) > 2:
        piva_candidates.append(clean_piva[2:])
    elif not clean_piva.startswith("IT"):
        piva_candidates.append(f"IT{clean_piva}")

    existing = await db.execute(
        select(Fornitore)
        .options(noload("*"))
        .where(Fornitore.partita_iva.in_(piva_candidates))
    )
    existing_supplier = existing.scalar_one_or_none()
    if existing_supplier:
        if existing_supplier.archived_at is None:
            raise HTTPException(status_code=409, detail=f"P.IVA fornitore '{existing_supplier.partita_iva}' già registrata per {existing_supplier.nome_azienda}")
        existing_supplier.nome_azienda = clean_nome
        existing_supplier.attivo_whitelist = data.attivo_whitelist
        existing_supplier.email_contatto = data.email_contatto
        existing_supplier.telefono_contatto = data.telefono_contatto.strip() if data.telefono_contatto else None
        existing_supplier.archived_at = None
        await db.flush()
        return existing_supplier

    fornitore = Fornitore(
        partita_iva=clean_piva,
        nome_azienda=clean_nome,
        attivo_whitelist=data.attivo_whitelist,
        email_contatto=data.email_contatto,
        telefono_contatto=data.telefono_contatto.strip() if data.telefono_contatto else None,
    )
    db.add(fornitore)
    await db.flush()
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
    result = await db.execute(
        select(Fornitore).options(noload("*")).where(
            Fornitore.id == fornitore_id,
            Fornitore.archived_at.is_(None),
        )
    )
    fornitore = result.scalar_one_or_none()
    if not fornitore:
        raise HTTPException(status_code=404, detail="Fornitore non trovato")
    return fornitore


@router.put(
    "/{fornitore_id}",
    response_model=FornitoreResponse,
    summary="Aggiorna fornitore",
)
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
    result = await db.execute(
        select(Fornitore).options(noload("*")).where(
            Fornitore.id == fornitore_id,
            Fornitore.archived_at.is_(None),
        )
    )
    fornitore = result.scalar_one_or_none()
    if not fornitore:
        raise HTTPException(status_code=404, detail="Fornitore non trovato")

    update_data = data.model_dump(exclude_unset=True)
    if "partita_iva" in update_data and update_data["partita_iva"]:
        clean_piva = update_data["partita_iva"].strip().upper()
        piva_candidates = [clean_piva]
        if clean_piva.startswith("IT") and len(clean_piva) > 2:
            piva_candidates.append(clean_piva[2:])
        elif not clean_piva.startswith("IT"):
            piva_candidates.append(f"IT{clean_piva}")

        existing = await db.execute(
            select(Fornitore)
            .options(noload("*"))
            .where(
                Fornitore.partita_iva.in_(piva_candidates),
                Fornitore.id != fornitore_id,
                Fornitore.archived_at.is_(None),
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"Partita IVA '{clean_piva}' già registrata per un altro fornitore",
            )
        update_data["partita_iva"] = clean_piva

    if "nome_azienda" in update_data and update_data["nome_azienda"]:
        update_data["nome_azienda"] = update_data["nome_azienda"].strip()

    if "telefono_contatto" in update_data and update_data["telefono_contatto"]:
        update_data["telefono_contatto"] = update_data["telefono_contatto"].strip()

    for key, value in update_data.items():
        setattr(fornitore, key, value)

    await db.flush()
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
    result = await db.execute(
        select(Fornitore).options(noload("*")).where(
            Fornitore.id == fornitore_id,
            Fornitore.archived_at.is_(None),
        )
    )
    fornitore = result.scalar_one_or_none()
    if not fornitore:
        raise HTTPException(status_code=404, detail="Fornitore non trovato")

    fornitore.attivo_whitelist = not fornitore.attivo_whitelist
    await db.flush()
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
    result = await db.execute(
        select(Fornitore).options(noload("*")).where(
            Fornitore.id == fornitore_id,
            Fornitore.archived_at.is_(None),
        )
    )
    fornitore = result.scalar_one_or_none()
    if not fornitore:
        raise HTTPException(status_code=404, detail="Fornitore non trovato")

    # Non cancellare mai lo storico commerciale. L'archiviazione rimuove il
    # fornitore dalle anagrafiche operative mantenendo intatti fatture, ordini,
    # listini, contestazioni e audit. La stessa P.IVA può essere ripristinata.
    fornitore.attivo_whitelist = False
    fornitore.archived_at = datetime.now(timezone.utc)
    await db.flush()
