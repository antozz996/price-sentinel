"""
Price Sentinel — Router Recensioni e Feedback Prodotti.
Permette agli operatori e responsabili di recensire i prodotti ordinati
e all'admin di gestire le segnalazioni e l'esclusione dal listino.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user, require_admin
from app.models.utenti import Utente
from app.models.products import Product, ProductFeedback
from app.models.listino import ListinoMaster
from app.models.fornitori import Fornitore

router = APIRouter()


# ── Pydantic Schemas ────────────────────────

class ProductFeedbackCreateRequest(BaseModel):
    product_id: int
    feedback: str = Field(..., pattern="^(SI|NO)$")
    rating: Optional[int] = Field(None, ge=1, le=5)
    motivo: Optional[str] = Field(None, max_length=255)
    note: Optional[str] = None
    ordine_id: Optional[int] = None


class FeedbackItemResponse(BaseModel):
    id: int
    user_id: int
    user_nome: str
    user_email: str
    user_ruolo: Optional[str]
    feedback: str
    rating: Optional[int]
    motivo: Optional[str]
    note: Optional[str]
    stato: str
    created_at: datetime
    admin_action: Optional[str] = None
    admin_notes: Optional[str] = None

    class Config:
        from_attributes = True


class ProductReviewItemResponse(BaseModel):
    product_id: int
    sku_interno: Optional[str]
    canonical_name: str
    order_name: Optional[str]
    category: Optional[str]
    subcategory: Optional[str]
    brand: Optional[str]
    comparison_unit: Optional[str]
    prezzo_riferimento: Optional[float] = None
    fornitore_abituale: Optional[str] = None
    
    # Statistiche Recensioni
    totale_feedback: int = 0
    positivi_si: int = 0
    negativi_no: int = 0
    rating_medio: Optional[float] = None
    
    # Recensione dell'utente corrente (se presente)
    mio_feedback: Optional[FeedbackItemResponse] = None
    
    # Tutte le recensioni recenti
    recensioni_recenti: List[FeedbackItemResponse] = []


class FeedbackResolveRequest(BaseModel):
    action: str = Field(..., pattern="^(escluso|archiviato|approvato)$")
    admin_notes: Optional[str] = None
    disattiva_prodotto: bool = False


# ── Endpoints ───────────────────────────────

@router.get("/prodotti", response_model=List[ProductReviewItemResponse])
async def get_prodotti_per_recensione(
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    filtro_recensione: Optional[str] = Query("tutti"),  # tutti, recensiti, da_recensire, segnalati_no
    db: AsyncSession = Depends(get_db),
    user: Utente = Depends(get_current_user)
):
    """
    Restituisce i prodotti arricchiti con le recensioni degli operatori e l'eventuale voto dell'utente corrente.
    """
    prod_query = select(Product).where(Product.is_active.is_(True))

    # Scoping settore se l'operatore non è admin
    if user.settore_abilitato and user.settore_abilitato != "all":
        allowed = [s.strip() for s in user.settore_abilitato.split(",") if s.strip()]
        if allowed:
            prod_query = prod_query.where(Product.category.in_(allowed))

    if category and category != "all" and category.strip():
        prod_query = prod_query.where(Product.category == category.strip())

    if search and search.strip():
        term = f"%{search.strip()}%"
        prod_query = prod_query.where(
            or_(
                Product.canonical_name.ilike(term),
                Product.order_name.ilike(term),
                Product.sku_interno.ilike(term),
                Product.brand.ilike(term)
            )
        )

    products = (await db.scalars(prod_query.order_by(Product.canonical_name))).all()
    if not products:
        return []

    product_ids = [p.id for p in products]

    # Carica tutti i feedbacks per questi prodotti
    feedbacks_stmt = (
        select(ProductFeedback)
        .where(ProductFeedback.product_id.in_(product_ids))
        .order_by(ProductFeedback.created_at.desc())
    )
    all_feedbacks = (await db.scalars(feedbacks_stmt)).all()

    # Mappa feedbacks per product_id
    feedbacks_by_prod: dict[int, list[ProductFeedback]] = {}
    for f in all_feedbacks:
        feedbacks_by_prod.setdefault(f.product_id, []).append(f)

    # Carica info fornitore abituale e listino
    sku_list = [p.sku_interno for p in products if p.sku_interno]
    listini = (await db.scalars(
        select(ListinoMaster)
        .where(ListinoMaster.sku_interno.in_(sku_list))
        .order_by(ListinoMaster.prezzo_pattuito.asc())
    )).all() if sku_list else []

    listino_map: dict[str, ListinoMaster] = {}
    for lm in listini:
        if lm.sku_interno and lm.sku_interno not in listino_map:
            listino_map[lm.sku_interno] = lm

    fornitori_db = (await db.scalars(select(Fornitore))).all()
    forn_name_map = {f.id: f.nome_azienda for f in fornitori_db}

    results: List[ProductReviewItemResponse] = []
    for p in products:
        p_feeds = feedbacks_by_prod.get(p.id, [])
        pos = sum(1 for f in p_feeds if f.feedback == "SI")
        neg = sum(1 for f in p_feeds if f.feedback == "NO")
        ratings = [f.rating for f in p_feeds if f.rating is not None]
        avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else None

        # Mio feedback
        mio = next((f for f in p_feeds if f.user_id == user.id), None)
        mio_resp = None
        if mio:
            u_nome = mio.user.nome_completo if mio.user and mio.user.nome_completo else (mio.user.email if mio.user else "Utente")
            mio_resp = FeedbackItemResponse(
                id=mio.id,
                user_id=mio.user_id,
                user_nome=u_nome,
                user_email=mio.user.email if mio.user else "",
                user_ruolo=mio.user.ruolo_dettagliato if mio.user else None,
                feedback=mio.feedback,
                rating=mio.rating,
                motivo=mio.motivo,
                note=mio.note,
                stato=mio.stato,
                created_at=mio.created_at,
                admin_action=mio.admin_action,
                admin_notes=mio.admin_notes,
            )

        # Recensioni recenti formattate
        recenti_resp: List[FeedbackItemResponse] = []
        for f in p_feeds[:5]:
            u_nome = f.user.nome_completo if f.user and f.user.nome_completo else (f.user.email if f.user else "Utente")
            recenti_resp.append(
                FeedbackItemResponse(
                    id=f.id,
                    user_id=f.user_id,
                    user_nome=u_nome,
                    user_email=f.user.email if f.user else "",
                    user_ruolo=f.user.ruolo_dettagliato if f.user else None,
                    feedback=f.feedback,
                    rating=f.rating,
                    motivo=f.motivo,
                    note=f.note,
                    stato=f.stato,
                    created_at=f.created_at,
                    admin_action=f.admin_action,
                    admin_notes=f.admin_notes,
                )
            )

        # Filtro stato recensione
        if filtro_recensione == "recensiti" and not p_feeds:
            continue
        if filtro_recensione == "da_recensire" and mio is not None:
            continue
        if filtro_recensione == "segnalati_no" and neg == 0:
            continue

        lm = listino_map.get(p.sku_interno or "")
        sup_name = forn_name_map.get(lm.fornitore_id) if lm and lm.fornitore_id else None
        price = float(lm.prezzo_pattuito) if lm and lm.prezzo_pattuito is not None else None

        results.append(
            ProductReviewItemResponse(
                product_id=p.id,
                sku_interno=p.sku_interno,
                canonical_name=p.canonical_name,
                order_name=p.order_name,
                category=p.category,
                subcategory=p.subcategory,
                brand=p.brand,
                comparison_unit=p.comparison_unit,
                prezzo_riferimento=price,
                fornitore_abituale=sup_name,
                totale_feedback=len(p_feeds),
                positivi_si=pos,
                negativi_no=neg,
                rating_medio=avg_rating,
                mio_feedback=mio_resp,
                recensioni_recenti=recenti_resp,
            )
        )

    return results


@router.post("/", response_model=FeedbackItemResponse)
async def crea_o_aggiorna_feedback(
    data: ProductFeedbackCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: Utente = Depends(get_current_user)
):
    """
    Crea o aggiorna la recensione di un prodotto da parte dell'utente loggato.
    """
    prod = await db.get(Product, data.product_id)
    if not prod:
        raise HTTPException(status_code=404, detail="Prodotto non trovato")

    # Verifica se l'utente ha già recensito questo prodotto
    stmt = select(ProductFeedback).where(
        ProductFeedback.product_id == data.product_id,
        ProductFeedback.user_id == user.id
    )
    existing = (await db.scalars(stmt)).first()

    if existing:
        existing.feedback = data.feedback
        existing.rating = data.rating
        existing.motivo = data.motivo
        existing.note = data.note
        existing.ordine_id = data.ordine_id or existing.ordine_id
        existing.stato = "in_attesa" if data.feedback == "NO" else "approvato"
        existing.created_at = datetime.utcnow()
        fb = existing
    else:
        fb = ProductFeedback(
            product_id=data.product_id,
            user_id=user.id,
            feedback=data.feedback,
            rating=data.rating,
            motivo=data.motivo,
            note=data.note,
            ordine_id=data.ordine_id,
            stato="in_attesa" if data.feedback == "NO" else "approvato",
            created_at=datetime.utcnow()
        )
        db.add(fb)

    await db.commit()
    await db.refresh(fb)

    u_nome = user.nome_completo or user.email
    return FeedbackItemResponse(
        id=fb.id,
        user_id=fb.user_id,
        user_nome=u_nome,
        user_email=user.email,
        user_ruolo=user.ruolo_dettagliato,
        feedback=fb.feedback,
        rating=fb.rating,
        motivo=fb.motivo,
        note=fb.note,
        stato=fb.stato,
        created_at=fb.created_at,
        admin_action=fb.admin_action,
        admin_notes=fb.admin_notes,
    )


@router.get("/pending-count")
async def get_pending_count(
    db: AsyncSession = Depends(get_db),
    _admin: Utente = Depends(require_admin)
):
    """
    Conteggio segnalazioni 'NO' in attesa per l'icona campanella dell'Admin.
    """
    stmt = select(func.count(ProductFeedback.id)).where(
        ProductFeedback.feedback == "NO",
        ProductFeedback.stato == "in_attesa"
    )
    count = (await db.scalar(stmt)) or 0
    return {"pending_count": count}


@router.get("/pending")
async def get_pending_feedbacks(
    db: AsyncSession = Depends(get_db),
    _admin: Utente = Depends(require_admin)
):
    """
    Elenco completo delle segnalazioni 'NO' in attesa per il pannello Admin.
    """
    stmt = (
        select(ProductFeedback)
        .where(
            ProductFeedback.feedback == "NO",
            ProductFeedback.stato == "in_attesa"
        )
        .order_by(ProductFeedback.created_at.desc())
    )
    feedbacks = (await db.scalars(stmt)).all()
    
    result = []
    for f in feedbacks:
        u_nome = f.user.nome_completo if f.user and f.user.nome_completo else (f.user.email if f.user else "Operatore")
        p_nome = f.product.canonical_name if f.product else "Prodotto"
        p_order = f.product.order_name if f.product else None
        p_cat = f.product.category if f.product else None
        p_sku = f.product.sku_interno if f.product else None

        result.append({
            "id": f.id,
            "product_id": f.product_id,
            "product_name": p_order or p_nome,
            "canonical_name": p_nome,
            "category": p_cat,
            "sku_interno": p_sku,
            "user_id": f.user_id,
            "user_nome": u_nome,
            "motivo": f.motivo,
            "note": f.note,
            "rating": f.rating,
            "created_at": f.created_at.isoformat() if f.created_at else None,
            "stato": f.stato
        })
    return result


@router.patch("/{feedback_id}/risolvi")
async def risolvi_feedback(
    feedback_id: int,
    data: FeedbackResolveRequest,
    db: AsyncSession = Depends(get_db),
    admin: Utente = Depends(require_admin)
):
    """
    L'admin gestisce la segnalazione: può escludere/archiviare il feedback
    ed eventualmente disattivare il prodotto dal catalogo.
    """
    fb = await db.get(ProductFeedback, feedback_id)
    if not fb:
        raise HTTPException(status_code=404, detail="Feedback non trovato")

    fb.stato = data.action  # "escluso" o "archiviato"
    fb.admin_action = data.action
    fb.admin_notes = data.admin_notes
    fb.resolved_at = datetime.utcnow()
    fb.resolved_by_id = admin.id

    if data.disattiva_prodotto and fb.product_id:
        prod = await db.get(Product, fb.product_id)
        if prod:
            prod.is_active = False

    await db.commit()
    return {"message": "Feedback gestito con successo", "stato": fb.stato}
