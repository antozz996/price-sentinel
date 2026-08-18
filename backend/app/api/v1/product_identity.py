from datetime import datetime, date
from decimal import Decimal
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select, delete, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, require_admin
from app.database import get_db
from app.models.utenti import Utente
from app.models.products import Product, SupplierProductAlias, MatchCandidate, ProductEquivalenceGroupItem
from app.models.fatture import RigaFattura, Fattura, StatoMatching
from app.models.fornitori import Fornitore
from app.models.anomalie import Anomalia, StatoValidazione
from app.services.normalization import extract_candidate_attributes, infer_category, normalize_text
from app.services.matching import normalize_price_for_comparison, _get_listino_attivo
from app.services.order_resolver import resolve_order_item

router = APIRouter()

# ──────────────────────────────────────────────────────────────────────
# Pydantic Schemas
# ──────────────────────────────────────────────────────────────────────

class ProductBase(BaseModel):
    sku_interno: Optional[str] = None
    canonical_name: str
    order_name: Optional[str] = Field(default=None, max_length=120)
    brand: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    variant: Optional[str] = None
    volume_ml: Optional[int] = None
    weight_g: Optional[int] = None
    unit_count: Optional[int] = 1
    container_type: Optional[str] = None
    comparison_unit: str
    is_commodity: Optional[bool] = False
    is_active: Optional[bool] = True

class ProductCreate(ProductBase):
    pass

class ProductUpdate(BaseModel):
    sku_interno: Optional[str] = None
    canonical_name: Optional[str] = None
    order_name: Optional[str] = Field(default=None, max_length=120)
    brand: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    variant: Optional[str] = None
    volume_ml: Optional[int] = None
    weight_g: Optional[int] = None
    unit_count: Optional[int] = None
    container_type: Optional[str] = None
    comparison_unit: Optional[str] = None
    is_commodity: Optional[bool] = None
    is_active: Optional[bool] = None

class ProductBulkClassificationUpdate(BaseModel):
    product_ids: List[int] = Field(min_length=1, max_length=1000)
    category: Optional[str] = Field(default=None, max_length=100)
    subcategory: Optional[str] = Field(default=None, max_length=100)

class ProductResponse(ProductBase):
    id: int
    normalized_name: Optional[str] = None
    normalized_order_name: Optional[str] = None
    supplier_pack_sizes: List[int] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ProductBulkClassificationResponse(BaseModel):
    updated_count: int
    products: List[ProductResponse]

class AliasCreate(BaseModel):
    supplier_id: int
    supplier_code: Optional[str] = None
    raw_description: str
    ean: Optional[str] = None
    pack_qty: Optional[int] = None
    volume_ml: Optional[int] = None
    weight_g: Optional[int] = None
    container_type: Optional[str] = None
    status: Optional[str] = "approved"

class AliasUpdate(BaseModel):
    pack_qty: Optional[int] = None
    volume_ml: Optional[int] = None
    weight_g: Optional[int] = None
    container_type: Optional[str] = None
    status: Optional[str] = None

class AliasResponse(BaseModel):
    id: int
    supplier_id: int
    product_id: int
    supplier_code: Optional[str] = None
    raw_description: str
    normalized_description: str
    ean: Optional[str] = None
    pack_qty: Optional[int] = None
    volume_ml: Optional[int] = None
    weight_g: Optional[int] = None
    container_type: Optional[str] = None
    status: str
    confidence_score: float
    source: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class CandidateResponse(BaseModel):
    id: int
    invoice_line_id: Optional[int] = None
    product_id: int
    source_type: str
    source_id: Optional[int] = None
    supplier_id: Optional[int] = None
    raw_description: Optional[str] = None
    normalized_description: Optional[str] = None
    score: float
    reason_json: Optional[dict] = None
    block_flag: bool
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

class WorkQueueResolutionProduct(BaseModel):
    canonical_name: str = Field(min_length=1, max_length=255)
    sku_interno: Optional[str] = Field(default=None, max_length=100)
    brand: Optional[str] = Field(default=None, max_length=100)
    category: Optional[str] = Field(default=None, max_length=100)
    subcategory: Optional[str] = Field(default=None, max_length=100)
    volume_ml: Optional[int] = Field(default=None, ge=1)
    weight_g: Optional[int] = Field(default=None, ge=1)
    unit_count: int = Field(default=1, ge=1)
    container_type: Optional[str] = Field(default=None, max_length=50)
    comparison_unit: str = Field(default="piece", max_length=50)

class WorkQueueResolutionRequest(BaseModel):
    invoice_line_ids: List[int] = Field(min_length=1, max_length=1000)
    action: str
    product_id: Optional[int] = None
    canonical_data: Optional[WorkQueueResolutionProduct] = None

class BulkWorkQueueResolutionRequest(BaseModel):
    items: List[WorkQueueResolutionRequest] = Field(min_length=1, max_length=500)

class OrderItemResolveRequest(BaseModel):
    query: str
    requested_qty: Optional[Decimal] = Decimal("1")
    requested_unit: Optional[str] = None
    allow_equivalent: Optional[bool] = False
    location_id: Optional[int] = None

class OrderOptimizeRequest(BaseModel):
    location_id: Optional[int] = None
    items: List[OrderItemResolveRequest]

# ──────────────────────────────────────────────────────────────────────
# Endpoints: Products
# ──────────────────────────────────────────────────────────────────────

@router.get("/products", response_model=List[ProductResponse], summary="Ottiene tutti i prodotti canonici")
async def list_products(
    db: AsyncSession = Depends(get_db),
    _user: Utente = Depends(get_current_user)
):
    stmt = select(Product).options(selectinload(Product.aliases)).order_by(Product.canonical_name)
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED, summary="Crea un prodotto canonico")
async def create_product(
    data: ProductCreate,
    db: AsyncSession = Depends(get_db),
    _admin: Utente = Depends(require_admin)
):
    norm_name = normalize_text(data.canonical_name)
    
    # Verifica duplicato
    if data.sku_interno:
        stmt = select(Product).where(Product.sku_interno == data.sku_interno)
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=400, detail="SKU interno già esistente")
    if data.order_name and data.order_name.strip():
        existing_order_name = await db.scalar(
            select(Product).where(
                Product.normalized_order_name == normalize_text(data.order_name)
            )
        )
        if existing_order_name:
            raise HTTPException(status_code=400, detail="Nome rapido già assegnato")

    product = Product(
        sku_interno=data.sku_interno,
        canonical_name=data.canonical_name,
        normalized_name=norm_name,
        order_name=data.order_name.strip() if data.order_name and data.order_name.strip() else None,
        normalized_order_name=normalize_text(data.order_name) if data.order_name and data.order_name.strip() else None,
        brand=data.brand,
        category=data.category,
        subcategory=data.subcategory,
        variant=data.variant,
        volume_ml=data.volume_ml,
        weight_g=data.weight_g,
        unit_count=data.unit_count,
        container_type=data.container_type,
        comparison_unit=data.comparison_unit,
        is_commodity=data.is_commodity,
        is_active=data.is_active
    )
    db.add(product)
    await db.flush()
    await db.refresh(product)
    return product

@router.patch(
    "/products/bulk-classification",
    response_model=ProductBulkClassificationResponse,
    summary="Aggiorna categoria e sottocategoria di più prodotti",
)
async def bulk_update_product_classification(
    data: ProductBulkClassificationUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: Utente = Depends(require_admin),
):
    fields_to_update = data.model_fields_set.intersection({"category", "subcategory"})
    if not fields_to_update:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Indicare almeno una tra categoria e sottocategoria",
        )

    product_ids = list(dict.fromkeys(data.product_ids))
    stmt = select(Product).where(Product.id.in_(product_ids))
    products = list((await db.execute(stmt)).scalars().all())
    found_ids = {product.id for product in products}
    missing_ids = [product_id for product_id in product_ids if product_id not in found_ids]
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": "Uno o più prodotti non sono stati trovati; nessuna modifica applicata",
                "missing_product_ids": missing_ids,
            },
        )

    for product in products:
        if "category" in fields_to_update:
            product.category = data.category.strip() if data.category and data.category.strip() else None
        if "subcategory" in fields_to_update:
            product.subcategory = data.subcategory.strip() if data.subcategory and data.subcategory.strip() else None

    await db.flush()

    updated_stmt = (
        select(Product)
        .where(Product.id.in_(product_ids))
        .options(selectinload(Product.aliases))
        .order_by(Product.canonical_name)
    )
    updated_products = list((await db.execute(updated_stmt)).scalars().all())
    return {
        "updated_count": len(updated_products),
        "products": updated_products,
    }

@router.patch("/products/{product_id}", response_model=ProductResponse, summary="Aggiorna un prodotto canonico")
async def update_product(
    product_id: int,
    data: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: Utente = Depends(require_admin)
):
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Prodotto non trovato")

    update_dict = data.model_dump(exclude_unset=True)
    if "canonical_name" in update_dict:
        update_dict["normalized_name"] = normalize_text(update_dict["canonical_name"])
    if "order_name" in update_dict:
        order_name = update_dict["order_name"]
        update_dict["order_name"] = order_name.strip() if order_name and order_name.strip() else None
        update_dict["normalized_order_name"] = normalize_text(order_name) if order_name and order_name.strip() else None
        if update_dict["normalized_order_name"]:
            existing_order_name = await db.scalar(
                select(Product).where(
                    Product.normalized_order_name == update_dict["normalized_order_name"],
                    Product.id != product_id,
                )
            )
            if existing_order_name:
                raise HTTPException(status_code=400, detail="Nome rapido già assegnato")

    for k, v in update_dict.items():
        setattr(product, k, v)

    await db.flush()
    await db.refresh(product)
    return product

# ──────────────────────────────────────────────────────────────────────
# Endpoints: Aliases
# ──────────────────────────────────────────────────────────────────────

@router.get("/products/{product_id}/aliases", response_model=List[AliasResponse], summary="Ottiene gli alias per un prodotto")
async def list_aliases(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    _user: Utente = Depends(get_current_user)
):
    stmt = select(SupplierProductAlias).where(SupplierProductAlias.product_id == product_id)
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("/products/{product_id}/aliases", response_model=AliasResponse, status_code=status.HTTP_201_CREATED, summary="Crea un alias per un prodotto")
async def create_alias(
    product_id: int,
    data: AliasCreate,
    db: AsyncSession = Depends(get_db),
    _admin: Utente = Depends(require_admin)
):
    # Verifica che il prodotto esista
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Prodotto non trovato")

    # Verifica duplicato
    if data.supplier_code:
        stmt = select(SupplierProductAlias).where(
            and_(
                SupplierProductAlias.supplier_id == data.supplier_id,
                SupplierProductAlias.supplier_code == data.supplier_code
            )
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=400, detail="Codice alias per questo fornitore già censito")

    alias = SupplierProductAlias(
        supplier_id=data.supplier_id,
        product_id=product_id,
        supplier_code=data.supplier_code,
        raw_description=data.raw_description,
        normalized_description=normalize_text(data.raw_description),
        ean=data.ean,
        pack_qty=data.pack_qty,
        volume_ml=data.volume_ml,
        weight_g=data.weight_g,
        container_type=data.container_type,
        status=data.status or "approved",
        source="manual",
        confidence_score=1.0
    )
    db.add(alias)
    await db.flush()
    await db.refresh(alias)
    return alias

@router.patch("/aliases/{alias_id}", response_model=AliasResponse, summary="Aggiorna un alias")
async def update_alias(
    alias_id: int,
    data: AliasUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: Utente = Depends(require_admin)
):
    alias = await db.get(SupplierProductAlias, alias_id)
    if not alias:
        raise HTTPException(status_code=404, detail="Alias non trovato")

    update_dict = data.model_dump(exclude_unset=True)
    for k, v in update_dict.items():
        setattr(alias, k, v)

    await db.flush()
    await db.refresh(alias)
    return alias

# ──────────────────────────────────────────────────────────────────────
# Endpoints: Match Candidates
# ──────────────────────────────────────────────────────────────────────

def _work_queue_signature(supplier_id: int, line: RigaFattura) -> tuple[int, str, str]:
    supplier_code = (line.codice_fornitore_raw or "").strip().upper()
    return (
        supplier_id,
        supplier_code,
        "" if supplier_code else normalize_text(line.descrizione_fornitore_raw or ""),
    )


@router.get(
    "/match-candidates/work-queue",
    summary="Ottiene la coda prodotti raggruppata per descrizione fornitore",
)
async def get_match_work_queue(
    db: AsyncSession = Depends(get_db),
    _admin: Utente = Depends(require_admin),
):
    """Una decisione operativa per prodotto, anche se ricorre su più fatture."""
    stmt = (
        select(RigaFattura, Fattura, Fornitore, MatchCandidate, Product)
        .join(Fattura, Fattura.id == RigaFattura.fattura_id)
        .join(Fornitore, Fornitore.id == Fattura.fornitore_id)
        .outerjoin(
            MatchCandidate,
            and_(
                MatchCandidate.invoice_line_id == RigaFattura.id,
                MatchCandidate.status == "pending",
            ),
        )
        .outerjoin(Product, Product.id == MatchCandidate.product_id)
        .where(RigaFattura.stato_matching == StatoMatching.in_parking)
        .order_by(Fattura.data_documento.desc(), RigaFattura.id.desc(), MatchCandidate.score.desc())
    )
    rows = (await db.execute(stmt)).all()

    groups: dict[tuple[int, str, str], dict[str, Any]] = {}
    weak_candidates_discarded = 0
    for line, invoice, supplier, candidate, product in rows:
        signature = _work_queue_signature(supplier.id, line)
        group = groups.setdefault(
            signature,
            {
                "supplier_id": supplier.id,
                "supplier_name": supplier.nome_azienda,
                "supplier_code": line.codice_fornitore_raw,
                "raw_description": line.descrizione_fornitore_raw or "Prodotto senza descrizione",
                "normalized_description": normalize_text(line.descrizione_fornitore_raw or ""),
                "invoice_line_ids": set(),
                "invoice_ids": set(),
                "latest_invoice_date": invoice.data_documento,
                "candidates": {},
                "candidate_records": 0,
            },
        )
        group["invoice_line_ids"].add(line.id)
        group["invoice_ids"].add(invoice.id)
        if invoice.data_documento > group["latest_invoice_date"]:
            group["latest_invoice_date"] = invoice.data_documento

        if not candidate or not product:
            continue

        group["candidate_records"] += 1
        reason = candidate.reason_json or {}
        is_blocked = bool(candidate.block_flag or reason.get("decision") == "parking")
        score = float(candidate.score)
        if score < 70 or is_blocked:
            weak_candidates_discarded += 1
            continue

        previous = group["candidates"].get(product.id)
        if previous is None or score > previous["score"]:
            group["candidates"][product.id] = {
                "candidate_id": candidate.id,
                "product_id": product.id,
                "sku_interno": product.sku_interno,
                "canonical_name": product.canonical_name,
                "score": round(score, 1),
                "reason_json": reason,
            }

    items = []
    for group in groups.values():
        alternatives = sorted(group["candidates"].values(), key=lambda item: item["score"], reverse=True)[:3]
        attributes = extract_candidate_attributes(group["raw_description"])
        best_candidate = alternatives[0] if alternatives else None
        items.append({
            "work_key": f"{group['supplier_id']}:{min(group['invoice_line_ids'])}",
            "supplier_id": group["supplier_id"],
            "supplier_name": group["supplier_name"],
            "supplier_code": group["supplier_code"],
            "raw_description": group["raw_description"],
            "normalized_description": group["normalized_description"],
            "occurrence_count": len(group["invoice_line_ids"]),
            "invoice_count": len(group["invoice_ids"]),
            "invoice_line_ids": sorted(group["invoice_line_ids"]),
            "latest_invoice_date": group["latest_invoice_date"],
            "candidate_records": group["candidate_records"],
            "recommendation": "associate_existing" if best_candidate else "create_canonical",
            "best_candidate": best_candidate,
            "alternatives": alternatives,
            "suggested_product": {
                "canonical_name": group["raw_description"].strip(),
                "category": attributes.get("category") or infer_category(group["raw_description"]),
                "volume_ml": attributes.get("volume_ml"),
                "weight_g": attributes.get("weight_g"),
                # Il formato 90x120 può indicare dimensioni, non 90 pezzi: il
                # numero confezione non viene mai presunto nella creazione rapida.
                "unit_count": 1,
                "container_type": attributes.get("container_type"),
                "comparison_unit": "piece",
            },
        })

    items.sort(key=lambda item: (-item["occurrence_count"], item["raw_description"].lower()))
    return {
        "summary": {
            "work_items": len(items),
            "invoice_lines": sum(item["occurrence_count"] for item in items),
            "reliable_suggestions": sum(1 for item in items if item["best_candidate"]),
            "probable_new_products": sum(1 for item in items if not item["best_candidate"]),
            "weak_candidates_hidden": weak_candidates_discarded,
        },
        "items": items,
    }


@router.post(
    "/match-candidates/work-queue/resolve",
    summary="Risolve insieme tutte le righe identiche della coda prodotti",
)
async def _resolve_single_work_item(db: AsyncSession, data: WorkQueueResolutionRequest) -> dict:
    allowed_actions = {"associate_existing", "create_canonical", "ignore"}
    if data.action not in allowed_actions:
        raise HTTPException(status_code=422, detail="Azione non supportata")
    if data.action == "associate_existing" and not data.product_id:
        raise HTTPException(status_code=422, detail="Selezionare il prodotto da associare")
    if data.action == "create_canonical" and not data.canonical_data:
        raise HTTPException(status_code=422, detail="Dati del nuovo prodotto mancanti")

    line_ids = list(dict.fromkeys(data.invoice_line_ids))
    line_stmt = (
        select(RigaFattura, Fattura)
        .join(Fattura, Fattura.id == RigaFattura.fattura_id)
        .where(RigaFattura.id.in_(line_ids))
    )
    line_rows = (await db.execute(line_stmt)).all()
    found_ids = {line.id for line, _invoice in line_rows}
    missing_ids = [line_id for line_id in line_ids if line_id not in found_ids]
    if missing_ids:
        raise HTTPException(
            status_code=404,
            detail={"message": "Alcune righe non esistono; nessuna modifica applicata", "missing_ids": missing_ids},
        )
    if any(line.stato_matching != StatoMatching.in_parking for line, _invoice in line_rows):
        raise HTTPException(status_code=409, detail="La coda è cambiata: ricaricare prima di procedere")

    signatures = {_work_queue_signature(invoice.fornitore_id, line) for line, invoice in line_rows}
    if len(signatures) != 1:
        raise HTTPException(status_code=422, detail="Le righe selezionate non rappresentano lo stesso prodotto fornitore")

    representative_line, representative_invoice = line_rows[0]
    product = None
    created_product = False

    if data.action == "ignore":
        for line, _invoice in line_rows:
            line.stato_matching = StatoMatching.no_match
        await db.execute(delete(MatchCandidate).where(MatchCandidate.invoice_line_id.in_(line_ids)))
        await db.flush()
        return {"status": "success", "resolved_lines": len(line_rows), "action": data.action}

    if data.action == "associate_existing":
        product = await db.get(Product, data.product_id)
        if not product or not product.is_active:
            raise HTTPException(status_code=404, detail="Prodotto canonico attivo non trovato")
    else:
        canonical = data.canonical_data
        if not canonical.canonical_name.strip():
            raise HTTPException(status_code=422, detail="Il nome canonico non può essere vuoto")
        sku = canonical.sku_interno.strip() if canonical.sku_interno and canonical.sku_interno.strip() else None
        if sku:
            duplicate = await db.scalar(select(Product.id).where(Product.sku_interno == sku))
            if duplicate:
                raise HTTPException(status_code=409, detail="SKU interno già esistente")
        if not sku:
            sku = f"CAN-{representative_invoice.fornitore_id}-{representative_line.id}-{int(datetime.utcnow().timestamp())}"

        product = Product(
            sku_interno=sku,
            canonical_name=canonical.canonical_name.strip(),
            normalized_name=normalize_text(canonical.canonical_name),
            brand=canonical.brand.strip() if canonical.brand else None,
            category=canonical.category.strip() if canonical.category else None,
            subcategory=canonical.subcategory.strip() if canonical.subcategory else None,
            volume_ml=canonical.volume_ml,
            weight_g=canonical.weight_g,
            unit_count=canonical.unit_count,
            container_type=canonical.container_type,
            comparison_unit=canonical.comparison_unit,
            is_commodity=False,
            is_active=True,
        )
        db.add(product)
        await db.flush()
        created_product = True

    normalized_description = normalize_text(representative_line.descrizione_fornitore_raw or "")
    alias_filters = [SupplierProductAlias.supplier_id == representative_invoice.fornitore_id]
    if representative_line.codice_fornitore_raw:
        alias_filters.append(SupplierProductAlias.supplier_code == representative_line.codice_fornitore_raw)
    else:
        alias_filters.append(SupplierProductAlias.normalized_description == normalized_description)
    alias = (await db.execute(select(SupplierProductAlias).where(and_(*alias_filters)))).scalars().first()
    attributes = extract_candidate_attributes(representative_line.descrizione_fornitore_raw or "")
    if alias:
        alias.product_id = product.id
        alias.raw_description = representative_line.descrizione_fornitore_raw or ""
        alias.normalized_description = normalized_description
        alias.status = "approved"
        alias.source = "manual"
        alias.confidence_score = 1.0
        alias.last_seen_at = datetime.utcnow()
    else:
        alias = SupplierProductAlias(
            supplier_id=representative_invoice.fornitore_id,
            product_id=product.id,
            supplier_code=representative_line.codice_fornitore_raw,
            raw_description=representative_line.descrizione_fornitore_raw or "",
            normalized_description=normalized_description,
            pack_qty=None,
            volume_ml=attributes.get("volume_ml"),
            weight_g=attributes.get("weight_g"),
            container_type=attributes.get("container_type"),
            status="approved",
            source="manual",
            confidence_score=1.0,
        )
        db.add(alias)
    await db.flush()

    for line, invoice in line_rows:
        line.sku_interno = product.sku_interno
        line.stato_matching = StatoMatching.matched
        if not product.sku_interno:
            continue
        listino = await _get_listino_attivo(
            db,
            invoice.fornitore_id,
            product.sku_interno,
            str(invoice.data_documento),
            supplier_alias_id=alias.id,
        )
        if not listino:
            continue
        normalized_price = normalize_price_for_comparison(
            line,
            product,
            alias=alias,
            target_comparison_unit=listino.unita_misura,
        )
        if not normalized_price.reliable:
            continue
        line.prezzo_netto_normalizzato = normalized_price.normalized_unit_price
        delta = line.prezzo_netto_normalizzato - Decimal(str(listino.prezzo_pattuito))
        await db.execute(delete(Anomalia).where(Anomalia.riga_fattura_id == line.id))
        if delta > 0:
            db.add(Anomalia(
                riga_fattura_id=line.id,
                delta_prezzo=delta,
                delta_totale=delta * line.quantita,
                prezzo_listino_snapshot=listino.prezzo_pattuito,
                prezzo_fatturato_snapshot=line.prezzo_netto_normalizzato,
                stato_validazione=StatoValidazione.da_verificare,
            ))

    await db.execute(delete(MatchCandidate).where(MatchCandidate.invoice_line_id.in_(line_ids)))
    await db.flush()
    return {
        "status": "success",
        "resolved_lines": len(line_rows),
        "action": data.action,
        "product_id": product.id,
        "product_name": product.canonical_name,
        "created_product": created_product,
    }


@router.post(
    "/match-candidates/work-queue/resolve",
    summary="Risolve insieme tutte le righe identiche della coda prodotti",
)
async def resolve_match_work_queue_item(
    data: WorkQueueResolutionRequest,
    db: AsyncSession = Depends(get_db),
    _admin: Utente = Depends(require_admin),
):
    res = await _resolve_single_work_item(db, data)
    await db.commit()
    return res


@router.post(
    "/match-candidates/work-queue/resolve-bulk",
    summary="Risolve massivamente più voci della coda prodotti",
)
async def resolve_match_work_queue_bulk(
    payload: BulkWorkQueueResolutionRequest,
    db: AsyncSession = Depends(get_db),
    _admin: Utente = Depends(require_admin),
):
    resolved_items = 0
    resolved_lines = 0
    errors = []

    for item in payload.items:
        try:
            res = await _resolve_single_work_item(db, item)
            resolved_items += 1
            resolved_lines += res.get("resolved_lines", 0)
        except Exception as e:
            errors.append(str(e))

    await db.commit()
    return {
        "status": "success",
        "resolved_items": resolved_items,
        "resolved_lines": resolved_lines,
        "errors": errors,
    }

@router.get("/match-candidates", response_model=List[CandidateResponse], summary="Ottiene l'elenco dei match candidate pendenti")
async def list_candidates(
    db: AsyncSession = Depends(get_db),
    _user: Utente = Depends(get_current_user)
):
    # I candidati associati a righe già risolte sono suggerimenti obsoleti e non
    # devono ricomparire nell'area di lavoro. I candidati da listino, che non hanno
    # invoice_line_id, restano invece visibili fino alla loro risoluzione.
    stmt = (
        select(MatchCandidate)
        .outerjoin(RigaFattura, RigaFattura.id == MatchCandidate.invoice_line_id)
        .where(
            MatchCandidate.status == "pending",
            or_(
                MatchCandidate.invoice_line_id.is_(None),
                RigaFattura.stato_matching == StatoMatching.in_parking,
            ),
        )
        .order_by(MatchCandidate.score.desc())
    )
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("/match-candidates/{candidate_id}/approve", summary="Approva una proposta di matching")
async def approve_candidate(
    candidate_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: Utente = Depends(require_admin)
):
    candidate = await db.get(MatchCandidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidato non trovato")

    product = await db.get(Product, candidate.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Prodotto canonico non trovato")

    # Determina i dettagli per creare/aggiornare l'alias
    supplier_id = candidate.supplier_id
    raw_desc = candidate.raw_description or ""
    supplier_code = None
    ean = None

    if candidate.invoice_line_id:
        riga = await db.get(RigaFattura, candidate.invoice_line_id)
        if riga:
            fattura = await db.get(Fattura, riga.fattura_id)
            if fattura:
                supplier_id = fattura.fornitore_id
            raw_desc = riga.descrizione_fornitore_raw or raw_desc
            supplier_code = riga.codice_fornitore_raw
            if riga.tipo_codice and riga.tipo_codice.upper() in ("EAN", "EAN13", "EAN8", "GTIN"):
                ean = riga.codice_fornitore_raw

    if not supplier_id:
        raise HTTPException(status_code=400, detail="Fornitore non identificabile dal candidato")

    # Verifica se l'alias esiste già o crealo
    alias_stmt = select(SupplierProductAlias).where(
        and_(
            SupplierProductAlias.supplier_id == supplier_id,
            SupplierProductAlias.raw_description == raw_desc
        )
    )
    alias_res = await db.execute(alias_stmt)
    alias = alias_res.scalar_one_or_none()

    if alias:
        alias.product_id = product.id
        alias.status = "approved"
        alias.last_seen_at = datetime.utcnow()
    else:
        alias = SupplierProductAlias(
            supplier_id=supplier_id,
            product_id=product.id,
            supplier_code=supplier_code,
            raw_description=raw_desc,
            normalized_description=normalize_text(raw_desc),
            ean=ean,
            status="approved",
            source="manual",
            confidence_score=1.0
        )
        db.add(alias)
    await db.flush()

    # Aggiorna la riga fattura originale se presente
    if candidate.invoice_line_id:
        riga = await db.get(RigaFattura, candidate.invoice_line_id)
        if riga:
            riga.sku_interno = product.sku_interno
            riga.stato_matching = StatoMatching.matched

            # Elimina tutti i candidati associati a questa riga
            await db.execute(delete(MatchCandidate).where(MatchCandidate.invoice_line_id == riga.id))

            # Calcola prezzi ed eventuali anomalie
            fattura = await db.get(Fattura, riga.fattura_id)
            if fattura:
                listino = await _get_listino_attivo(
                    db,
                    fattura.fornitore_id,
                    product.sku_interno,
                    str(fattura.data_documento),
                    supplier_alias_id=alias.id,
                )
                if listino:
                    norm_price_res = normalize_price_for_comparison(
                        riga,
                        product,
                        alias=alias,
                        target_comparison_unit=listino.unita_misura,
                    )
                    if norm_price_res.reliable:
                        riga.prezzo_netto_normalizzato = norm_price_res.normalized_unit_price
                        delta = riga.prezzo_netto_normalizzato - Decimal(str(listino.prezzo_pattuito))
                        if delta > 0:
                            # Pulisce vecchie anomalie
                            await db.execute(delete(Anomalia).where(Anomalia.riga_fattura_id == riga.id))
                            # Crea nuova anomalia
                            anomalia = Anomalia(
                                riga_fattura_id=riga.id,
                                delta_prezzo=delta,
                                delta_totale=delta * riga.quantita,
                                prezzo_listino_snapshot=listino.prezzo_pattuito,
                                prezzo_fatturato_snapshot=riga.prezzo_netto_normalizzato,
                                stato_validazione=StatoValidazione.da_verificare,
                            )
                            db.add(anomalia)
            # Calcola prezzi ed eventuali anomalie... (riga)
            pass

    if candidate.source_type == "price_list_row" and candidate.reason_json:
        price_val = candidate.reason_json.get("price")
        uom_val = candidate.reason_json.get("uom") or product.comparison_unit or "piece"
        if price_val is not None:
            if alias.id is None:
                await db.flush()
            from app.services.supplier_list_import import save_append_only_price
            await save_append_only_price(
                db=db,
                fornitore_id=supplier_id,
                sku_interno=product.sku_interno,
                descrizione=raw_desc,
                prezzo_pattuito=Decimal(str(price_val)),
                unita_misura=uom_val,
                data_inizio=date.today(),
                supplier_product_alias_id=alias.id
            )

    candidate.status = "approved"
    candidate.resolved_at = datetime.utcnow()
    await db.flush()

    return {"message": f"Matching approvato con successo. Prodotto associato allo SKU {product.sku_interno}"}

@router.post("/match-candidates/{candidate_id}/reject", summary="Rifiuta una proposta di matching")
async def reject_candidate(
    candidate_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: Utente = Depends(require_admin)
):
    candidate = await db.get(MatchCandidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidato non trovato")

    candidate.status = "rejected"
    candidate.resolved_at = datetime.utcnow()
    await db.flush()
    return {"message": "Proposta di matching rifiutata"}

@router.post("/product-identity/import-supplier-list/{supplier_id}", summary="Importa un listino prezzi concordato da un file Excel")
async def import_supplier_list(
    supplier_id: int,
    file: UploadFile = File(...),
    dry_run: bool = Query(True, description="Esegue l'importazione in modalità dry run (simulazione)"),
    create_missing_products: bool = Query(
        False,
        description="Crea in modo controllato i prodotti canonici mancanti durante il primo listino",
    ),
    db: AsyncSession = Depends(get_db),
    _admin: Utente = Depends(require_admin)
):
    file_bytes = await file.read()
    from app.services.supplier_list_import import import_supplier_list_excel
    res = await import_supplier_list_excel(
        db=db,
        supplier_id=supplier_id,
        file_bytes=file_bytes,
        dry_run=dry_run,
        create_missing_products=create_missing_products,
    )
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

# ──────────────────────────────────────────────────────────────────────

@router.post("/orders/resolve-item", summary="Risolve un singolo articolo preventivo trovando il fornitore migliore")
async def resolve_item(
    req: OrderItemResolveRequest,
    db: AsyncSession = Depends(get_db),
    _user: Utente = Depends(get_current_user)
):
    res = await resolve_order_item(
        db=db,
        query=req.query,
        requested_qty=req.requested_qty,
        allow_equivalent=req.allow_equivalent,
        location_id=req.location_id
    )
    return res

@router.post("/orders/optimize", summary="Ottimizza un carrello d'acquisto preventivo massivo")
async def optimize_basket(
    req: OrderOptimizeRequest,
    db: AsyncSession = Depends(get_db),
    _user: Utente = Depends(get_current_user)
):
    righe_ottimizzate = []
    avvisi_preventivi = []
    spesa_totale_blindata = Decimal("0")
    risparmio_preventivo_stimato = Decimal("0")
    numero_anomalie = 0

    for item in req.items:
        res = await resolve_order_item(
            db=db,
            query=item.query,
            requested_qty=item.requested_qty,
            requested_unit=item.requested_unit,
            allow_equivalent=item.allow_equivalent,
            location_id=req.location_id
        )

        if res["decision"] in {"resolved", "needs_manual_selection"} and res["best_offer"]:
            best = res["best_offer"]
            tipo_regola = "spot_ottimale" if best["source_type"] == "spot" else "concordato"
            
            if res["alternatives"]:
                worst = res["alternatives"][-1]
                risparmio = Decimal(worst["estimated_total"]) - Decimal(best["estimated_total"])
                risparmio_preventivo_stimato += risparmio

            spesa_totale_blindata += Decimal(best["estimated_total"])

            confronto = [
                {
                    "fornitore_id": best["supplier_id"],
                    "fornitore_name": best["supplier_name"],
                    "fornitore_nome": best["supplier_name"],
                    "prezzo": float(best["unit_price_normalized"])
                }
            ]
            for alt in res["alternatives"]:
                confronto.append({
                    "fornitore_id": alt["supplier_id"],
                    "fornitore_name": alt["supplier_name"],
                    "fornitore_nome": alt["supplier_name"],
                    "prezzo": float(alt["unit_price_normalized"])
                })

            righe_ottimizzate.append({
                "sku_interno": res["matched_product"]["sku_interno"],
                "descrizione": best["supplier_product_name"],
                "quantita": float(item.requested_qty),
                "prezzo_inserito": float(best["price_per_pack"]),
                "prezzo_ottimale": float(best["price_per_pack"]),
                "tipo_regola": tipo_regola,
                "fornitore_id": best["supplier_id"],
                "fornitore_name": best["supplier_name"],
                "fornitore_nome": best["supplier_name"],
                "is_anomalia": False,
                "is_policy_deviation": False,
                "requires_manual_selection": res["requires_manual_selection"],
                "absolute_cheapest": res["absolute_cheapest"],
                "recommended_offer": res["recommended_offer"],
                "selected_offer": res["selected_offer"],
                "purchase_policy": res["purchase_policy"],
                "recommendation_reason": res["recommendation_reason"],
                "confronto_prezzi": confronto
            })
        else:
            avvisi_preventivi.append(f"Prodotto '{item.query}' in parking area o non associato.")
            numero_anomalie += 1
            righe_ottimizzate.append({
                "sku_interno": res["matched_product"]["sku_interno"] if res["matched_product"] else item.query,
                "descrizione": f"Articolo non risolto: {item.query}",
                "quantita": float(item.requested_qty),
                "prezzo_inserito": 0.0,
                "prezzo_ottimale": 0.0,
                "tipo_regola": "sconosciuto",
                "fornitore_id": 0,
                "fornitore_name": "Nessuno",
                "fornitore_nome": "Nessuno",
                "is_anomalia": True,
                "is_policy_deviation": False,
                "dettaglio_anomalia": "Articolo non associato al catalogo canonico",
                "confronto_prezzi": []
            })

    return {
        "righe_ottimizzate": righe_ottimizzate,
        "sintesi": {
            "spesa_totale_blindata": float(spesa_totale_blindata),
            "risparmio_preventivo_stimato": float(risparmio_preventivo_stimato),
            "numero_anomalie": numero_anomalie,
            "avvisi_preventivi": avvisi_preventivi
        }
    }
