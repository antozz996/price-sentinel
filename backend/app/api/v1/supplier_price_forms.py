from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
from hashlib import sha256
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, require_admin
from app.database import get_db
from app.models.fornitori import Fornitore
from app.models.listino import ListinoMaster
from app.models.supplier_price_form import SupplierPriceFormItem, SupplierPriceFormRequest
from app.models.utenti import Utente

router = APIRouter()


def _require_primary_tenant(user: Utente) -> None:
    # Supplier and contract records are currently global legacy tables.
    if getattr(user, "tenant_id", None) != 1:
        raise HTTPException(status_code=403, detail="Moduli listino non ancora disponibili per questa azienda")


def _request_view(request: SupplierPriceFormRequest) -> dict:
    return {
        "id": request.id,
        "supplier_id": request.supplier_id,
        "supplier_name": request.supplier.nome_azienda if request.supplier else None,
        "status": request.status,
        "created_at": request.created_at.isoformat(),
        "expires_at": request.expires_at.isoformat(),
        "submitted_at": request.submitted_at.isoformat() if request.submitted_at else None,
        "note": request.note,
        "items": [
            {
                "id": item.id,
                "listino_id": item.listino_id,
                "sku_interno": item.sku_interno,
                "descrizione": item.descrizione,
                "prezzo_corrente": str(item.prezzo_corrente),
                "unita_corrente": item.unita_corrente,
                "validita_corrente_da": item.validita_corrente_da.isoformat(),
                "validita_corrente_a": item.validita_corrente_a.isoformat() if item.validita_corrente_a else None,
                "prezzo_inviato": str(item.prezzo_inviato) if item.prezzo_inviato is not None else None,
                "unita_inviata": item.unita_inviata,
                "conferma_prezzo": item.conferma_prezzo,
                "nota_fornitore": item.nota_fornitore,
                "esito": (
                    "da_compilare" if item.prezzo_inviato is None
                    else "confermato" if item.conferma_prezzo
                    else "proposta_variazione"
                ),
            }
            for item in request.items
        ],
    }


class CreateFormRequest(BaseModel):
    supplier_id: int
    listino_ids: list[int] = Field(min_length=1, max_length=2000)
    expires_in_days: int = Field(default=14, ge=1, le=30)
    note: Optional[str] = Field(default=None, max_length=1000)


class SupplierAnswer(BaseModel):
    item_id: int
    prezzo: Decimal = Field(gt=0, lt=Decimal("100000000"), decimal_places=4)
    unita_misura: str = Field(min_length=1, max_length=50)
    conferma_prezzo: bool
    nota: Optional[str] = Field(default=None, max_length=1000)


class PublicSubmission(BaseModel):
    answers: list[SupplierAnswer] = Field(min_length=1, max_length=2000)


@router.get("/public/{token}", summary="Visualizza il modulo listino del fornitore")
async def get_public_form(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    if len(token) < 40 or len(token) > 100:
        raise HTTPException(status_code=404, detail="Modulo non trovato")
    token_hash = sha256(token.encode("utf-8")).hexdigest()
    request = (await db.execute(
        select(SupplierPriceFormRequest)
        .options(selectinload(SupplierPriceFormRequest.supplier), selectinload(SupplierPriceFormRequest.items))
        .where(SupplierPriceFormRequest.token_hash == token_hash)
    )).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if not request or request.status != "open" or request.expires_at <= now:
        raise HTTPException(status_code=404, detail="Link non valido, scaduto o già inviato")
    return {
        "supplier_name": request.supplier.nome_azienda,
        "expires_at": request.expires_at.isoformat(),
        "note": request.note,
        "items": [
            {
                "id": item.id,
                "sku_interno": item.sku_interno,
                "descrizione": item.descrizione,
                "prezzo_corrente": str(item.prezzo_corrente),
                "unita_corrente": item.unita_corrente,
                "validita_corrente_da": item.validita_corrente_da.isoformat(),
                "validita_corrente_a": item.validita_corrente_a.isoformat() if item.validita_corrente_a else None,
            }
            for item in request.items
        ],
    }


@router.post("/public/{token}/submit", summary="Invia la conferma o la proposta del fornitore")
async def submit_public_form(
    token: str,
    payload: PublicSubmission,
    db: AsyncSession = Depends(get_db),
):
    if len(token) < 40 or len(token) > 100:
        raise HTTPException(status_code=404, detail="Modulo non trovato")
    token_hash = sha256(token.encode("utf-8")).hexdigest()
    request = (await db.execute(
        select(SupplierPriceFormRequest)
        .options(selectinload(SupplierPriceFormRequest.items))
        .where(SupplierPriceFormRequest.token_hash == token_hash)
        .with_for_update()
    )).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if not request or request.status != "open" or request.expires_at <= now:
        raise HTTPException(status_code=404, detail="Link non valido, scaduto o già inviato")

    answers_by_id = {answer.item_id: answer for answer in payload.answers}
    if len(answers_by_id) != len(payload.answers):
        raise HTTPException(status_code=422, detail="Il modulo contiene righe duplicate")
    expected_ids = {item.id for item in request.items}
    if set(answers_by_id) != expected_ids:
        raise HTTPException(status_code=422, detail="Compila tutte le righe del modulo senza modificarne l'identità")

    for item in request.items:
        answer = answers_by_id[item.id]
        unit = answer.unita_misura.strip()
        if not unit:
            raise HTTPException(status_code=422, detail=f"Unità di misura mancante per {item.sku_interno}")
        same_price = answer.prezzo == item.prezzo_corrente
        same_unit = unit.casefold() == item.unita_corrente.strip().casefold()
        if answer.conferma_prezzo and not (same_price and same_unit):
            raise HTTPException(
                status_code=422,
                detail=f"La riga {item.sku_interno} è indicata come confermata ma prezzo o unità sono diversi dal pattuito",
            )
        item.prezzo_inviato = answer.prezzo
        item.unita_inviata = unit
        item.conferma_prezzo = answer.conferma_prezzo
        item.nota_fornitore = answer.nota.strip() if answer.nota else None

    request.status = "submitted"
    request.submitted_at = now
    await db.commit()
    return {"status": "submitted", "message": "Risposta inviata. Nessun prezzo nel listino master è stato modificato."}


@router.post("/", status_code=status.HTTP_201_CREATED, summary="Crea un modulo per un fornitore")
async def create_form_request(
    payload: CreateFormRequest,
    admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _require_primary_tenant(admin)
    if len(set(payload.listino_ids)) != len(payload.listino_ids):
        raise HTTPException(status_code=422, detail="La selezione contiene righe duplicate")

    supplier = await db.get(Fornitore, payload.supplier_id)
    if not supplier or supplier.archived_at is not None:
        raise HTTPException(status_code=404, detail="Fornitore non trovato o archiviato")

    today = datetime.now(ZoneInfo("Europe/Rome")).date()
    rows = (await db.execute(
        select(ListinoMaster)
        .where(
            ListinoMaster.id.in_(payload.listino_ids),
            ListinoMaster.fornitore_id == payload.supplier_id,
            ListinoMaster.data_inizio_validita <= today,
            (ListinoMaster.data_scadenza.is_(None)) | (ListinoMaster.data_scadenza >= today),
        )
        .order_by(ListinoMaster.sku_interno)
    )).scalars().all()
    if len(rows) != len(payload.listino_ids):
        raise HTTPException(
            status_code=422,
            detail="Una o più righe non appartengono al fornitore o non sono attive oggi",
        )

    token = secrets.token_urlsafe(36)
    now = datetime.now(timezone.utc)
    request = SupplierPriceFormRequest(
        supplier_id=supplier.id,
        created_by_id=admin.id,
        token_hash=sha256(token.encode("utf-8")).hexdigest(),
        status="open",
        created_at=now,
        expires_at=now + timedelta(days=payload.expires_in_days),
        note=payload.note.strip() if payload.note else None,
        items=[
            SupplierPriceFormItem(
                listino_id=row.id,
                sku_interno=row.sku_interno,
                descrizione=row.descrizione,
                prezzo_corrente=row.prezzo_pattuito,
                unita_corrente=row.unita_misura,
                validita_corrente_da=row.data_inizio_validita,
                validita_corrente_a=row.data_scadenza,
            )
            for row in rows
        ],
    )
    db.add(request)
    await db.commit()
    request = (await db.execute(
        select(SupplierPriceFormRequest)
        .options(selectinload(SupplierPriceFormRequest.supplier), selectinload(SupplierPriceFormRequest.items))
        .where(SupplierPriceFormRequest.id == request.id)
    )).scalar_one()
    return {
        "request": _request_view(request),
        "token": token,
        "public_path": f"/fornitore/listino/{token}",
    }


@router.get("/", summary="Elenca i moduli listino")
async def list_form_requests(
    status_filter: str = Query(default="all", pattern="^(all|open|submitted|expired|closed)$"),
    admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _require_primary_tenant(admin)
    query = (
        select(SupplierPriceFormRequest)
        .options(selectinload(SupplierPriceFormRequest.supplier), selectinload(SupplierPriceFormRequest.items))
        .order_by(SupplierPriceFormRequest.created_at.desc())
    )
    records = (await db.execute(query)).scalars().unique().all()
    now = datetime.now(timezone.utc)
    result = []
    for request in records:
        if status_filter != "all" and request.status != status_filter:
            continue
        if request.status == "open" and request.expires_at <= now:
            request.status = "expired"
        result.append(_request_view(request))
    await db.commit()
    return result


@router.get("/{request_id}", summary="Dettaglio risposta a un modulo listino")
async def get_form_request(
    request_id: int,
    admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _require_primary_tenant(admin)
    request = (await db.execute(
        select(SupplierPriceFormRequest)
        .options(selectinload(SupplierPriceFormRequest.supplier), selectinload(SupplierPriceFormRequest.items))
        .where(SupplierPriceFormRequest.id == request_id)
    )).scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Modulo non trovato")
    if request.status == "open" and request.expires_at <= datetime.now(timezone.utc):
        request.status = "expired"
        await db.commit()
    return _request_view(request)


@router.post("/{request_id}/close", summary="Chiude un modulo listino")
async def close_form_request(
    request_id: int,
    admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _require_primary_tenant(admin)
    request = (await db.execute(select(SupplierPriceFormRequest).where(SupplierPriceFormRequest.id == request_id).with_for_update())).scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Modulo non trovato")
    if request.status not in {"open", "submitted", "expired"}:
        raise HTTPException(status_code=409, detail="Modulo già chiuso")
    request.status = "closed"
    await db.commit()
    return {"id": request.id, "status": request.status}
