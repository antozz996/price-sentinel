from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
from hashlib import sha256
import secrets
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, require_admin
from app.database import get_db
from app.models.fornitori import Fornitore
from app.models.listino import ListinoMaster
from app.models.products import Product
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
        "request_type": request.request_type,
        "created_at": request.created_at.isoformat(),
        "expires_at": request.expires_at.isoformat(),
        "submitted_at": request.submitted_at.isoformat() if request.submitted_at else None,
        "note": request.note,
        "validita_inviata_da": request.validita_inviata_da.isoformat() if request.validita_inviata_da else None,
        "validita_inviata_a": request.validita_inviata_a.isoformat() if request.validita_inviata_a else None,
        "items": [
            {
                "id": item.id,
                "listino_id": item.listino_id,
                "sku_interno": item.sku_interno,
                "descrizione": item.descrizione,
                "prezzo_corrente": str(item.prezzo_corrente) if item.prezzo_corrente is not None else None,
                "unita_corrente": item.unita_corrente,
                "brand_corrente": item.brand_corrente,
                "validita_corrente_da": item.validita_corrente_da.isoformat() if item.validita_corrente_da else None,
                "validita_corrente_a": item.validita_corrente_a.isoformat() if item.validita_corrente_a else None,
                "prezzo_inviato": str(item.prezzo_inviato) if item.prezzo_inviato is not None else None,
                "unita_inviata": item.unita_inviata,
                "brand_inviata": item.brand_inviata,
                "dicitura_inviata": item.dicitura_inviata,
                "quantita_inviata": str(item.quantita_inviata) if item.quantita_inviata is not None else None,
                "conferma_prezzo": item.conferma_prezzo,
                "nota_fornitore": item.nota_fornitore,
                "non_trattato": item.non_trattato,
                "esito": (
                    "non_trattato" if item.non_trattato
                    else "da_compilare" if item.prezzo_inviato is None
                    else "nuova_offerta" if request.request_type == "new_listino"
                    else "confermato" if item.conferma_prezzo
                    else "proposta_variazione"
                ),
            }
            for item in request.items
        ],
    }


class CreateFormRequest(BaseModel):
    supplier_id: int
    request_type: Literal["confirmation", "new_listino"] = "confirmation"
    listino_ids: list[int] = Field(default_factory=list, max_length=2000)
    product_ids: list[int] = Field(default_factory=list, max_length=2000)
    category: Optional[str] = Field(default=None, max_length=100)
    expires_in_days: int = Field(default=14, ge=1, le=30)
    note: Optional[str] = Field(default=None, max_length=1000)


class SupplierAnswer(BaseModel):
    item_id: int
    prezzo: Decimal | None = Field(default=None, gt=0, lt=Decimal("100000000"), decimal_places=4)
    unita_misura: str | None = Field(default=None, min_length=1, max_length=50)
    marca: str | None = Field(default=None, max_length=100)
    dicitura_fornitore: str | None = Field(default=None, max_length=500)
    quantita_confezione: Decimal | None = Field(default=None, gt=0, lt=Decimal("100000000"), decimal_places=3)
    conferma_prezzo: bool = False
    non_trattato: bool = False
    nota: Optional[str] = Field(default=None, max_length=1000)


class PublicSubmission(BaseModel):
    answers: list[SupplierAnswer] = Field(min_length=1, max_length=2000)
    # Optional for compatibility with supplier pages opened before this release.
    validita_inviata_da: date | None = None
    validita_inviata_a: date | None = None


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
        "request_type": request.request_type,
        "expires_at": request.expires_at.isoformat(),
        "note": request.note,
        "items": [
            {
                "id": item.id,
                "sku_interno": item.sku_interno,
                "descrizione": item.descrizione,
                "prezzo_corrente": str(item.prezzo_corrente) if item.prezzo_corrente is not None else None,
                "unita_corrente": item.unita_corrente,
                "brand_corrente": item.brand_corrente,
                "validita_corrente_da": item.validita_corrente_da.isoformat() if item.validita_corrente_da else None,
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
    if payload.validita_inviata_da is None:
        raise HTTPException(status_code=422, detail="Indica la data di inizio dell'offerta")
    if (
        payload.validita_inviata_da
        and payload.validita_inviata_a
        and payload.validita_inviata_a < payload.validita_inviata_da
    ):
        raise HTTPException(status_code=422, detail="La data di fine validità deve essere successiva o uguale alla data di inizio")

    answers_by_id = {answer.item_id: answer for answer in payload.answers}
    if len(answers_by_id) != len(payload.answers):
        raise HTTPException(status_code=422, detail="Il modulo contiene righe duplicate")
    expected_ids = {item.id for item in request.items}
    if set(answers_by_id) != expected_ids:
        raise HTTPException(status_code=422, detail="Compila tutte le righe del modulo senza modificarne l'identità")

    for item in request.items:
        answer = answers_by_id[item.id]
        item.nota_fornitore = answer.nota.strip() if answer.nota else None
        item.brand_inviata = answer.marca.strip() if answer.marca else None
        item.dicitura_inviata = answer.dicitura_fornitore.strip() if answer.dicitura_fornitore else None
        item.quantita_inviata = answer.quantita_confezione
        if answer.non_trattato:
            if answer.conferma_prezzo:
                raise HTTPException(status_code=422, detail="Un prodotto non trattato non può essere confermato")
            item.non_trattato = True
            item.prezzo_inviato = None
            item.unita_inviata = None
            item.brand_inviata = None
            item.dicitura_inviata = None
            item.quantita_inviata = None
            item.conferma_prezzo = False
            continue
        if answer.prezzo is None:
            raise HTTPException(status_code=422, detail=f"Inserisci un prezzo oppure indica che non tratti {item.sku_interno}")
        unit = (answer.unita_misura or "").strip()
        if not unit:
            raise HTTPException(status_code=422, detail=f"Unità di misura mancante per {item.sku_interno}")
        if not item.brand_inviata:
            raise HTTPException(status_code=422, detail=f"Marca mancante per {item.sku_interno}; indica la marca oppure 'senza marca'")
        if not item.dicitura_inviata:
            raise HTTPException(status_code=422, detail=f"Dicitura fornitore mancante per {item.sku_interno}")
        if item.quantita_inviata is None:
            raise HTTPException(status_code=422, detail=f"Quantità confezione mancante per {item.sku_interno}")
        same_price = item.prezzo_corrente is not None and answer.prezzo == item.prezzo_corrente
        same_unit = item.unita_corrente is not None and unit.casefold() == item.unita_corrente.strip().casefold()
        if request.request_type == "new_listino" and answer.conferma_prezzo:
            raise HTTPException(status_code=422, detail="Una nuova offerta non può essere marcata come conferma")
        if answer.conferma_prezzo and not (same_price and same_unit):
            raise HTTPException(
                status_code=422,
                detail=f"La riga {item.sku_interno} è indicata come confermata ma prezzo o unità sono diversi dal pattuito",
            )
        item.non_trattato = False
        item.prezzo_inviato = answer.prezzo
        item.unita_inviata = unit
        item.conferma_prezzo = answer.conferma_prezzo

    request.status = "submitted"
    request.submitted_at = now
    request.validita_inviata_da = payload.validita_inviata_da
    request.validita_inviata_a = payload.validita_inviata_a
    await db.commit()
    message = (
        "Nuova offerta inviata con validità indicata. È in attesa di revisione; nessun prezzo ufficiale è stato modificato."
        if request.request_type == "new_listino"
        else "Risposta inviata con il periodo di validità indicato. Nessun prezzo nel listino master è stato modificato."
    )
    return {"status": "submitted", "message": message}


@router.post("/", status_code=status.HTTP_201_CREATED, summary="Crea un modulo per un fornitore")
async def create_form_request(
    payload: CreateFormRequest,
    admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _require_primary_tenant(admin)
    supplier = await db.get(Fornitore, payload.supplier_id)
    if not supplier or supplier.archived_at is not None:
        raise HTTPException(status_code=404, detail="Fornitore non trovato o archiviato")

    if payload.request_type == "new_listino":
        if not payload.category or not payload.product_ids or payload.listino_ids:
            raise HTTPException(status_code=422, detail="Per una nuova richiesta indica categoria e prodotti, senza righe listino esistenti")
        if len(set(payload.product_ids)) != len(payload.product_ids):
            raise HTTPException(status_code=422, detail="La selezione contiene prodotti duplicati")
        products = (await db.execute(
            select(Product)
            .where(
                Product.id.in_(payload.product_ids),
                func.lower(Product.category) == payload.category.strip().lower(),
                Product.is_active.is_(True),
            )
            .order_by(Product.canonical_name)
        )).scalars().all()
        if len(products) != len(payload.product_ids):
            raise HTTPException(status_code=422, detail="Uno o più prodotti non appartengono alla categoria selezionata o non sono attivi")
        form_items = [
            SupplierPriceFormItem(
                listino_id=None,
                sku_interno=product.sku_interno or f"PROD-{product.id}",
                descrizione=product.canonical_name,
                prezzo_corrente=None,
                unita_corrente=product.comparison_unit,
                brand_corrente=product.brand,
                validita_corrente_da=None,
                validita_corrente_a=None,
            )
            for product in products
        ]
    else:
        if not payload.listino_ids or payload.product_ids or payload.category:
            raise HTTPException(status_code=422, detail="Per confermare un listino seleziona solo le sue righe attive")
        if len(set(payload.listino_ids)) != len(payload.listino_ids):
            raise HTTPException(status_code=422, detail="La selezione contiene righe duplicate")
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
        sku_values = {row.sku_interno for row in rows if row.sku_interno}
        products = (await db.execute(select(Product).where(Product.sku_interno.in_(sku_values)))).scalars().all() if sku_values else []
        brand_by_sku = {product.sku_interno: product.brand for product in products}
        form_items = [
            SupplierPriceFormItem(
                listino_id=row.id,
                sku_interno=row.sku_interno,
                descrizione=row.descrizione,
                prezzo_corrente=row.prezzo_pattuito,
                unita_corrente=row.unita_misura,
                brand_corrente=brand_by_sku.get(row.sku_interno),
                validita_corrente_da=row.data_inizio_validita,
                validita_corrente_a=row.data_scadenza,
            )
            for row in rows
        ]

    token = secrets.token_urlsafe(36)
    now = datetime.now(timezone.utc)
    request = SupplierPriceFormRequest(
        supplier_id=supplier.id,
        created_by_id=admin.id,
        request_type=payload.request_type,
        token_hash=sha256(token.encode("utf-8")).hexdigest(),
        status="open",
        created_at=now,
        expires_at=now + timedelta(days=payload.expires_in_days),
        note=payload.note.strip() if payload.note else None,
        items=form_items,
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


@router.get("/catalog-products", summary="Elenca i prodotti attivi del catalogo per una nuova richiesta listino")
async def get_catalog_products(
    category: str = Query(min_length=1, max_length=100),
    admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _require_primary_tenant(admin)
    products = (await db.execute(
        select(Product)
        .where(func.lower(Product.category) == category.strip().lower(), Product.is_active.is_(True))
        .order_by(Product.canonical_name)
    )).scalars().all()
    return [
        {
            "id": product.id,
            "sku_interno": product.sku_interno or f"PROD-{product.id}",
            "descrizione": product.canonical_name,
            "unita_misura": product.comparison_unit,
            "category": product.category,
            "subcategory": product.subcategory,
        }
        for product in products
    ]


@router.get("/catalog/{supplier_id}", summary="Elenca il listino del fornitore raggruppato per categoria")
async def get_supplier_catalog(
    supplier_id: int,
    admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _require_primary_tenant(admin)
    supplier = await db.get(Fornitore, supplier_id)
    if not supplier or supplier.archived_at is not None:
        raise HTTPException(status_code=404, detail="Fornitore non trovato o archiviato")

    today = datetime.now(ZoneInfo("Europe/Rome")).date()
    rows = (await db.execute(
        select(ListinoMaster)
        .where(
            ListinoMaster.fornitore_id == supplier_id,
            ListinoMaster.data_inizio_validita <= today,
            (ListinoMaster.data_scadenza.is_(None)) | (ListinoMaster.data_scadenza >= today),
        )
        .order_by(ListinoMaster.sku_interno)
    )).scalars().all()

    categories_by_sku: dict[str, tuple[str | None, str | None]] = {}
    sku_values = {row.sku_interno for row in rows if row.sku_interno}
    if sku_values:
        products = (await db.execute(
            select(Product.sku_interno, Product.category, Product.subcategory)
            .where(Product.sku_interno.in_(sku_values), Product.is_active.is_(True))
            .order_by(Product.id.desc())
        )).all()
        for sku, category, subcategory in products:
            categories_by_sku.setdefault(sku, (category, subcategory))

    return [
        {
            "id": row.id,
            "sku_interno": row.sku_interno,
            "descrizione": row.descrizione,
            "prezzo_pattuito": str(row.prezzo_pattuito),
            "unita_misura": row.unita_misura,
            "data_inizio_validita": row.data_inizio_validita.isoformat(),
            "data_scadenza": row.data_scadenza.isoformat() if row.data_scadenza else None,
            "category": categories_by_sku.get(row.sku_interno, (None, None))[0],
            "subcategory": categories_by_sku.get(row.sku_interno, (None, None))[1],
        }
        for row in rows
    ]


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


@router.delete("/{request_id}", status_code=status.HTTP_200_OK, summary="Elimina un modulo listino e revoca il link")
async def delete_form_request(
    request_id: int,
    admin: Utente = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _require_primary_tenant(admin)
    request = (await db.execute(
        select(SupplierPriceFormRequest)
        .options(selectinload(SupplierPriceFormRequest.items))
        .where(SupplierPriceFormRequest.id == request_id)
        .with_for_update()
    )).scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Modulo non trovato")

    # Removing the request cascades to its response snapshot items and revokes
    # the public token. It never alters the referenced official listino rows.
    await db.delete(request)
    await db.commit()
    return {"id": request_id, "deleted": True}

