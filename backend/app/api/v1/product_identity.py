from datetime import datetime, date
from decimal import Decimal
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, File, UploadFile
from pydantic import BaseModel
from sqlalchemy import select, delete, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, require_admin
from app.database import get_db
from app.models.utenti import Utente
from app.models.products import Product, SupplierProductAlias, MatchCandidate, ProductEquivalenceGroupItem
from app.models.fatture import RigaFattura, Fattura, StatoMatching
from app.models.anomalie import Anomalia, StatoValidazione
from app.services.normalization import normalize_text
from app.services.matching import normalize_price_for_comparison, _get_listino_attivo
from app.services.order_resolver import resolve_order_item

router = APIRouter()

# ──────────────────────────────────────────────────────────────────────
# Pydantic Schemas
# ──────────────────────────────────────────────────────────────────────

class ProductBase(BaseModel):
    sku_interno: Optional[str] = None
    canonical_name: str
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

class ProductResponse(ProductBase):
    id: int
    normalized_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

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
    stmt = select(Product).order_by(Product.canonical_name)
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

    product = Product(
        sku_interno=data.sku_interno,
        canonical_name=data.canonical_name,
        normalized_name=norm_name,
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

@router.get("/match-candidates", response_model=List[CandidateResponse], summary="Ottiene l'elenco dei match candidate pendenti")
async def list_candidates(
    db: AsyncSession = Depends(get_db),
    _user: Utente = Depends(get_current_user)
):
    stmt = select(MatchCandidate).where(MatchCandidate.status == "pending").order_by(MatchCandidate.score.desc())
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
                listino = await _get_listino_attivo(db, fattura.fornitore_id, product.sku_interno, str(fattura.data_documento))
                if listino:
                    norm_price_res = normalize_price_for_comparison(riga, product)
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
            from app.services.supplier_list_import import save_append_only_price
            await save_append_only_price(
                db=db,
                fornitore_id=supplier_id,
                sku_interno=product.sku_interno,
                descrizione=raw_desc,
                prezzo_pattuito=Decimal(str(price_val)),
                unita_misura=uom_val,
                data_inizio=date.today()
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
    db: AsyncSession = Depends(get_db),
    _admin: Utente = Depends(require_admin)
):
    file_bytes = await file.read()
    from app.services.supplier_list_import import import_supplier_list_excel
    res = await import_supplier_list_excel(db=db, supplier_id=supplier_id, file_bytes=file_bytes)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

# ──────────────────────────────────────────────────────────────────────
# Endpoints: Orders & Optimization
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

        if res["decision"] == "resolved":
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
                    "prezzo": float(best["unit_price_normalized"])
                }
            ]
            for alt in res["alternatives"]:
                confronto.append({
                    "fornitore_id": alt["supplier_id"],
                    "fornitore_name": alt["supplier_name"],
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
                "is_anomalia": False,
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
                "is_anomalia": True,
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
