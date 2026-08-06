"""Smart Price Sheet, supplier assessments and purchase policy API."""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.api.deps import get_current_user, require_admin
from app.database import get_db
from app.models.fatture import Fattura, RigaFattura
from app.models.fornitori import Fornitore
from app.models.listino import ListinoMaster
from app.models.location import Location
from app.models.products import Product
from app.models.purchase_policy import (
    ProductPurchasePolicy,
    ProductPurchasePolicyAudit,
    ProductSupplierAssessment,
    ProductSupplierAssessmentAudit,
    PurchasePolicyDeviation,
)
from app.models.utenti import Utente
from app.schemas.smart_price_sheet import (
    AssessmentUpsertRequest,
    CellPreviewRequest,
    ClipboardPreviewRequest,
    CommitPreviewRequest,
    DeviationCreateRequest,
    DeviationUpdateRequest,
    PolicyUpsertRequest,
)
from app.services.purchase_recommendation import (
    policy_snapshot,
    rank_supplier_offers,
)
from app.services.smart_price_sheet import build_price_preview, commit_price_preview


router = APIRouter()


def _scope_location(user: Utente, requested: int | None) -> int | None:
    if user.ruolo.value == "manager":
        if user.location_id is None:
            raise HTTPException(403, "Manager senza sede associata")
        if requested is not None and requested != user.location_id:
            raise HTTPException(403, "Accesso consentito solo alla propria sede")
        return user.location_id
    return requested


def _preview_response(preview) -> dict:
    return {
        "preview_token": str(preview.id),
        "status": preview.status,
        "expires_at": preview.expires_at,
        "payload_hash": preview.payload_hash,
        **preview.preview_payload,
        "commit_result": preview.commit_result,
    }


def _assessment_state(row: ProductSupplierAssessment) -> dict:
    return {
        "product_id": row.product_id,
        "supplier_id": row.supplier_id,
        "location_id": row.location_id,
        "status": row.status,
        "quality_score": row.quality_score,
        "delivery_reliability_score": (
            str(row.delivery_reliability_score)
            if row.delivery_reliability_score is not None
            else None
        ),
        "reason": row.reason,
        "is_active": row.is_active,
        "valid_from": row.valid_from.isoformat(),
        "valid_to": row.valid_to.isoformat() if row.valid_to else None,
    }


def _policy_state(row: ProductPurchasePolicy) -> dict:
    return {
        "product_id": row.product_id,
        "location_id": row.location_id,
        "selection_mode": row.selection_mode,
        "preferred_supplier_id": row.preferred_supplier_id,
        "minimum_quality": row.minimum_quality,
        "max_price_premium_percent": str(row.max_price_premium_percent),
        "max_price_premium_absolute": str(row.max_price_premium_absolute),
        "allow_spot": row.allow_spot,
        "reason": row.reason,
        "is_active": row.is_active,
        "valid_from": row.valid_from.isoformat(),
        "valid_to": row.valid_to.isoformat() if row.valid_to else None,
    }


async def _validate_entities(
    db: AsyncSession,
    *,
    product_id: int,
    supplier_id: int | None = None,
    location_id: int | None = None,
) -> None:
    if not await db.get(Product, product_id):
        raise HTTPException(404, "Prodotto non trovato")
    if supplier_id is not None:
        supplier = await db.scalar(
            select(Fornitore).options(noload("*")).where(Fornitore.id == supplier_id)
        )
        if not supplier:
            raise HTTPException(404, "Fornitore non trovato")
    if location_id is not None:
        location = await db.scalar(
            select(Location).options(noload("*")).where(Location.id == location_id)
        )
        if not location:
            raise HTTPException(404, "Sede non trovata")


@router.get("/matrix")
async def matrix(
    search: str | None = Query(default=None, max_length=150),
    category: str | None = Query(default=None, max_length=100),
    location_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: Utente = Depends(get_current_user),
):
    scope = _scope_location(user, location_id)
    product_filter = [Product.is_active.is_(True)]
    if search:
        term = f"%{search.strip()}%"
        product_filter.append(
            or_(Product.canonical_name.ilike(term), Product.sku_interno.ilike(term))
        )
    if category:
        product_filter.append(Product.category == category)
    total = await db.scalar(
        select(func.count()).select_from(Product).where(*product_filter)
    )
    products = (
        await db.scalars(
            select(Product)
            .where(*product_filter)
            .order_by(Product.canonical_name, Product.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    suppliers = (
        await db.scalars(
            select(Fornitore)
            .options(noload("*"))
            .where(Fornitore.attivo_whitelist.is_(True))
            .order_by(Fornitore.nome_azienda, Fornitore.id)
        )
    ).all()
    product_ids = [row.id for row in products]
    skus = [row.sku_interno for row in products if row.sku_interno]
    supplier_ids = [row.id for row in suppliers]
    today = date.today()

    active_prices = []
    spot_prices = []
    assessments = []
    policies = []
    if skus and supplier_ids:
        active_prices = (
            await db.scalars(
                select(ListinoMaster)
                .options(noload("*"))
                .where(
                    ListinoMaster.sku_interno.in_(skus),
                    ListinoMaster.fornitore_id.in_(supplier_ids),
                    ListinoMaster.data_inizio_validita <= today,
                    or_(
                        ListinoMaster.data_scadenza.is_(None),
                        ListinoMaster.data_scadenza >= today,
                    ),
                )
                .order_by(
                    ListinoMaster.sku_interno,
                    ListinoMaster.fornitore_id,
                    ListinoMaster.data_inizio_validita.desc(),
                    ListinoMaster.id.desc(),
                )
            )
        ).all()
        spot_prices = (
            await db.execute(
                select(
                    RigaFattura.sku_interno,
                    Fattura.fornitore_id,
                    func.min(RigaFattura.prezzo_netto_normalizzato).label("price"),
                )
                .join(Fattura, RigaFattura.fattura_id == Fattura.id)
                .where(
                    RigaFattura.sku_interno.in_(skus),
                    Fattura.fornitore_id.in_(supplier_ids),
                    RigaFattura.prezzo_netto_normalizzato > 0,
                    RigaFattura.is_omaggio.is_not(True),
                )
                .group_by(RigaFattura.sku_interno, Fattura.fornitore_id)
            )
        ).all()
    if product_ids:
        assessment_scope = ProductSupplierAssessment.location_id.is_(None)
        policy_scope = ProductPurchasePolicy.location_id.is_(None)
        if scope is not None:
            assessment_scope = or_(
                ProductSupplierAssessment.location_id == scope,
                ProductSupplierAssessment.location_id.is_(None),
            )
            policy_scope = or_(
                ProductPurchasePolicy.location_id == scope,
                ProductPurchasePolicy.location_id.is_(None),
            )
        assessments = (
            await db.scalars(
                select(ProductSupplierAssessment)
                .where(ProductSupplierAssessment.product_id.in_(product_ids), assessment_scope)
                .where(
                    ProductSupplierAssessment.is_active.is_(True),
                    ProductSupplierAssessment.valid_from <= today,
                    or_(
                        ProductSupplierAssessment.valid_to.is_(None),
                        ProductSupplierAssessment.valid_to >= today,
                    ),
                )
                .order_by(
                    ProductSupplierAssessment.product_id,
                    case((ProductSupplierAssessment.location_id.is_not(None), 0), else_=1),
                    ProductSupplierAssessment.id.desc(),
                )
            )
        ).all()
        policies = (
            await db.scalars(
                select(ProductPurchasePolicy)
                .where(ProductPurchasePolicy.product_id.in_(product_ids), policy_scope)
                .where(
                    ProductPurchasePolicy.is_active.is_(True),
                    ProductPurchasePolicy.valid_from <= today,
                    or_(
                        ProductPurchasePolicy.valid_to.is_(None),
                        ProductPurchasePolicy.valid_to >= today,
                    ),
                )
                .order_by(
                    ProductPurchasePolicy.product_id,
                    case((ProductPurchasePolicy.location_id.is_not(None), 0), else_=1),
                    ProductPurchasePolicy.id.desc(),
                )
            )
        ).all()

    effective_assessments: dict[int, dict[int, dict]] = {}
    for row in assessments:
        by_supplier = effective_assessments.setdefault(row.product_id, {})
        by_supplier.setdefault(
            row.supplier_id,
            {
                **_assessment_state(row),
                "scope": "location" if row.location_id is not None else "global",
            },
        )
    effective_policies: dict[int, dict] = {}
    for row in policies:
        effective_policies.setdefault(row.product_id, policy_snapshot(row))

    prices: dict[tuple[str, int], dict] = {}
    for sku, supplier_id, price in spot_prices:
        prices[(sku, supplier_id)] = {
            "supplier_id": supplier_id,
            "unit_price_normalized": f"{Decimal(str(price)):.4f}",
            "price": f"{Decimal(str(price)):.4f}",
            "source_type": "spot",
            "uom": None,
        }
    for row in active_prices:
        key = (row.sku_interno, row.fornitore_id)
        if key in prices and prices[key].get("source_type") == "contratto":
            continue
        prices[key] = {
            "supplier_id": row.fornitore_id,
            "unit_price_normalized": f"{Decimal(str(row.prezzo_pattuito)):.4f}",
            "price": f"{Decimal(str(row.prezzo_pattuito)):.4f}",
            "source_type": "contratto",
            "uom": row.unita_misura,
            "listino_id": row.id,
            "valid_from": row.data_inizio_validita.isoformat(),
            "valid_to": row.data_scadenza.isoformat() if row.data_scadenza else None,
        }

    supplier_names = {row.id: row.nome_azienda for row in suppliers}
    rows = []
    for product in products:
        offers = []
        if product.sku_interno:
            for supplier in suppliers:
                offer = prices.get((product.sku_interno, supplier.id))
                if offer:
                    offers.append({**offer, "supplier_name": supplier.nome_azienda})
        recommendation = rank_supplier_offers(
            offers,
            effective_assessments.get(product.id, {}),
            effective_policies.get(product.id),
        )
        rows.append(
            {
                "product_id": product.id,
                "sku_interno": product.sku_interno,
                "canonical_name": product.canonical_name,
                "category": product.category,
                "subcategory": product.subcategory,
                "comparison_unit": product.comparison_unit,
                "offers": {str(item["supplier_id"]): item for item in recommendation["offers"]},
                "absolute_cheapest_supplier_id": (
                    recommendation["absolute_cheapest"]["supplier_id"]
                    if recommendation["absolute_cheapest"]
                    else None
                ),
                "recommended_supplier_id": (
                    recommendation["recommended_offer"]["supplier_id"]
                    if recommendation["recommended_offer"]
                    else None
                ),
                "selected_supplier_id": (
                    recommendation["selected_offer"]["supplier_id"]
                    if recommendation["selected_offer"]
                    else None
                ),
                "recommendation_reason": recommendation["recommendation_reason"],
                "requires_manual_selection": recommendation["requires_manual_selection"],
                "policy": recommendation["policy"],
            }
        )
    return {
        "total": total or 0,
        "limit": limit,
        "offset": offset,
        "location_id": scope,
        "suppliers": [
            {"id": row.id, "name": row.nome_azienda, "vat": row.partita_iva}
            for row in suppliers
        ],
        "supplier_names": supplier_names,
        "rows": rows,
    }


@router.post("/preview")
async def preview_clipboard(
    payload: ClipboardPreviewRequest,
    db: AsyncSession = Depends(get_db),
    user: Utente = Depends(require_admin),
):
    scope = _scope_location(user, payload.location_id)
    try:
        preview = await build_price_preview(
            db,
            text_value=payload.text,
            supplier_mapping=payload.supplier_mapping,
            product_mapping=payload.product_mapping,
            effective_date=payload.effective_date,
            default_uom=payload.default_uom,
            location_id=scope,
            actor_id=user.id,
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return _preview_response(preview)


@router.post("/cell-preview")
async def preview_cell(
    payload: CellPreviewRequest,
    db: AsyncSession = Depends(get_db),
    user: Utente = Depends(require_admin),
):
    product = await db.get(Product, payload.product_id)
    supplier = await db.scalar(
        select(Fornitore).options(noload("*")).where(Fornitore.id == payload.supplier_id)
    )
    if not product or not supplier:
        raise HTTPException(404, "Prodotto o fornitore non trovato")
    scope = _scope_location(user, payload.location_id)
    text_value = f"Prodotto\t{supplier.nome_azienda}\n{product.canonical_name}\t{payload.price}"
    preview = await build_price_preview(
        db,
        text_value=text_value,
        supplier_mapping={supplier.nome_azienda: supplier.id},
        product_mapping={product.canonical_name: product.id},
        effective_date=payload.effective_date,
        default_uom=payload.uom,
        location_id=scope,
        actor_id=user.id,
    )
    return _preview_response(preview)


@router.post("/commit")
async def commit_preview(
    payload: CommitPreviewRequest,
    db: AsyncSession = Depends(get_db),
    user: Utente = Depends(require_admin),
):
    if payload.confirm is not True:
        raise HTTPException(422, "Conferma esplicita obbligatoria")
    preview, result = await commit_price_preview(db, payload.preview_token, user.id)
    return {
        "preview_token": str(preview.id),
        "status": preview.status,
        "committed_at": preview.committed_at,
        "result": result,
    }


@router.get("/assessments")
async def list_assessments(
    product_id: int | None = Query(default=None, gt=0),
    location_id: int | None = Query(default=None, gt=0),
    db: AsyncSession = Depends(get_db),
    user: Utente = Depends(get_current_user),
):
    scope = _scope_location(user, location_id)
    statement = (
        select(ProductSupplierAssessment, Product.canonical_name, Fornitore.nome_azienda)
        .join(Product, Product.id == ProductSupplierAssessment.product_id)
        .join(Fornitore, Fornitore.id == ProductSupplierAssessment.supplier_id)
    )
    if product_id:
        statement = statement.where(ProductSupplierAssessment.product_id == product_id)
    if scope is None:
        statement = statement.where(ProductSupplierAssessment.location_id.is_(None))
    else:
        statement = statement.where(
            or_(
                ProductSupplierAssessment.location_id == scope,
                ProductSupplierAssessment.location_id.is_(None),
            )
        )
    rows = (await db.execute(statement.order_by(Product.canonical_name, Fornitore.nome_azienda))).all()
    return [
        {
            "id": row.id,
            **_assessment_state(row),
            "product_name": product_name,
            "supplier_name": supplier_name,
            "scope": "location" if row.location_id is not None else "global",
            "updated_at": row.updated_at,
        }
        for row, product_name, supplier_name in rows
    ]


@router.put("/assessments")
async def upsert_assessment(
    payload: AssessmentUpsertRequest,
    db: AsyncSession = Depends(get_db),
    user: Utente = Depends(require_admin),
):
    await _validate_entities(
        db,
        product_id=payload.product_id,
        supplier_id=payload.supplier_id,
        location_id=payload.location_id,
    )
    scope_filter = ProductSupplierAssessment.location_id.is_(None)
    if payload.location_id is not None:
        scope_filter = ProductSupplierAssessment.location_id == payload.location_id
    row = await db.scalar(
        select(ProductSupplierAssessment)
        .where(
            ProductSupplierAssessment.product_id == payload.product_id,
            ProductSupplierAssessment.supplier_id == payload.supplier_id,
            scope_filter,
        )
        .with_for_update()
    )
    now = datetime.now(timezone.utc)
    before = _assessment_state(row) if row else None
    if row:
        action = "updated"
        row.status = payload.status
        row.quality_score = payload.quality_score
        row.delivery_reliability_score = payload.delivery_reliability_score
        row.reason = (payload.reason or "").strip() or None
        row.is_active = payload.is_active
        row.valid_from = payload.valid_from
        row.valid_to = payload.valid_to
        row.updated_by = user.id
        row.updated_at = now
    else:
        action = "created"
        row = ProductSupplierAssessment(
            product_id=payload.product_id,
            supplier_id=payload.supplier_id,
            location_id=payload.location_id,
            status=payload.status,
            quality_score=payload.quality_score,
            delivery_reliability_score=payload.delivery_reliability_score,
            reason=(payload.reason or "").strip() or None,
            is_active=payload.is_active,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            created_by=user.id,
            updated_by=user.id,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        await db.flush()
    after = _assessment_state(row)
    db.add(
        ProductSupplierAssessmentAudit(
            assessment_id=row.id,
            action=action,
            before_state=before,
            after_state=after,
            actor_id=user.id,
            occurred_at=now,
        )
    )
    await db.flush()
    return {"id": row.id, **after, "action": action, "updated_at": row.updated_at}


@router.get("/policies")
async def list_policies(
    product_id: int | None = Query(default=None, gt=0),
    location_id: int | None = Query(default=None, gt=0),
    db: AsyncSession = Depends(get_db),
    user: Utente = Depends(get_current_user),
):
    scope = _scope_location(user, location_id)
    statement = select(ProductPurchasePolicy, Product.canonical_name).join(
        Product, Product.id == ProductPurchasePolicy.product_id
    )
    if product_id:
        statement = statement.where(ProductPurchasePolicy.product_id == product_id)
    if scope is None:
        statement = statement.where(ProductPurchasePolicy.location_id.is_(None))
    else:
        statement = statement.where(
            or_(
                ProductPurchasePolicy.location_id == scope,
                ProductPurchasePolicy.location_id.is_(None),
            )
        )
    rows = (await db.execute(statement.order_by(Product.canonical_name))).all()
    return [
        {
            "id": row.id,
            **_policy_state(row),
            "product_name": product_name,
            "scope": "location" if row.location_id is not None else "global",
            "updated_at": row.updated_at,
        }
        for row, product_name in rows
    ]


@router.put("/policies")
async def upsert_policy(
    payload: PolicyUpsertRequest,
    db: AsyncSession = Depends(get_db),
    user: Utente = Depends(require_admin),
):
    await _validate_entities(
        db, product_id=payload.product_id, location_id=payload.location_id
    )
    if payload.preferred_supplier_id is not None:
        preferred_supplier = await db.scalar(
            select(Fornitore)
            .options(noload("*"))
            .where(Fornitore.id == payload.preferred_supplier_id)
        )
        if not preferred_supplier:
            raise HTTPException(404, "Fornitore preferito non trovato")
    scope_filter = ProductPurchasePolicy.location_id.is_(None)
    if payload.location_id is not None:
        scope_filter = ProductPurchasePolicy.location_id == payload.location_id
    row = await db.scalar(
        select(ProductPurchasePolicy)
        .where(ProductPurchasePolicy.product_id == payload.product_id, scope_filter)
        .with_for_update()
    )
    now = datetime.now(timezone.utc)
    before = _policy_state(row) if row else None
    values = payload.model_dump()
    if row:
        action = "updated"
        for field, value in values.items():
            if field not in {"product_id", "location_id"}:
                setattr(row, field, value)
        row.updated_by = user.id
        row.updated_at = now
    else:
        action = "created"
        row = ProductPurchasePolicy(
            **values,
            created_by=user.id,
            updated_by=user.id,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        await db.flush()
    after = _policy_state(row)
    db.add(
        ProductPurchasePolicyAudit(
            policy_id=row.id,
            action=action,
            before_state=before,
            after_state=after,
            actor_id=user.id,
            occurred_at=now,
        )
    )
    await db.flush()
    return {"id": row.id, **after, "action": action, "updated_at": row.updated_at}


@router.get("/history")
async def history(
    product_id: int | None = Query(default=None, gt=0),
    supplier_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    _: Utente = Depends(get_current_user),
):
    statement = (
        select(ListinoMaster, Fornitore.nome_azienda)
        .options(noload("*"))
        .join(Fornitore, Fornitore.id == ListinoMaster.fornitore_id)
        .order_by(ListinoMaster.data_inizio_validita.desc(), ListinoMaster.id.desc())
        .limit(limit)
    )
    if supplier_id:
        statement = statement.where(ListinoMaster.fornitore_id == supplier_id)
    if product_id:
        product = await db.get(Product, product_id)
        if not product or not product.sku_interno:
            return []
        statement = statement.where(ListinoMaster.sku_interno == product.sku_interno)
    rows = (await db.execute(statement)).all()
    return [
        {
            "id": row.id,
            "supplier_id": row.fornitore_id,
            "supplier_name": supplier_name,
            "sku_interno": row.sku_interno,
            "description": row.descrizione,
            "price": f"{Decimal(str(row.prezzo_pattuito)):.4f}",
            "uom": row.unita_misura,
            "valid_from": row.data_inizio_validita,
            "valid_to": row.data_scadenza,
            "active": row.data_scadenza is None,
        }
        for row, supplier_name in rows
    ]


@router.get("/audit")
async def audit(
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    _: Utente = Depends(require_admin),
):
    assessment_rows = (
        await db.scalars(
            select(ProductSupplierAssessmentAudit)
            .order_by(ProductSupplierAssessmentAudit.occurred_at.desc())
            .limit(limit)
        )
    ).all()
    policy_rows = (
        await db.scalars(
            select(ProductPurchasePolicyAudit)
            .order_by(ProductPurchasePolicyAudit.occurred_at.desc())
            .limit(limit)
        )
    ).all()
    combined = [
        {
            "entity_type": "assessment",
            "entity_id": str(row.assessment_id),
            "action": row.action,
            "actor_id": row.actor_id,
            "occurred_at": row.occurred_at,
            "before_state": row.before_state,
            "after_state": row.after_state,
        }
        for row in assessment_rows
    ] + [
        {
            "entity_type": "policy",
            "entity_id": str(row.policy_id),
            "action": row.action,
            "actor_id": row.actor_id,
            "occurred_at": row.occurred_at,
            "before_state": row.before_state,
            "after_state": row.after_state,
        }
        for row in policy_rows
    ]
    return sorted(combined, key=lambda item: item["occurred_at"], reverse=True)[:limit]


@router.get("/deviations")
async def list_deviations(
    location_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    user: Utente = Depends(get_current_user),
):
    scope = _scope_location(user, location_id)
    statement = select(PurchasePolicyDeviation)
    if scope is not None:
        statement = statement.where(PurchasePolicyDeviation.location_id == scope)
    rows = (
        await db.scalars(
            statement.order_by(PurchasePolicyDeviation.occurred_at.desc()).limit(limit)
        )
    ).all()
    return [
        {
            "id": str(row.id),
            "dedupe_key": row.dedupe_key,
            "product_id": row.product_id,
            "location_id": row.location_id,
            "recommended_supplier_id": row.recommended_supplier_id,
            "selected_supplier_id": row.selected_supplier_id,
            "actual_supplier_id": row.actual_supplier_id,
            "absolute_cheapest_supplier_id": row.absolute_cheapest_supplier_id,
            "deviation_type": row.deviation_type,
            "status": row.status,
            "reason": row.reason,
            "context": row.context,
            "actual_normalized_price": str(row.actual_normalized_price) if row.actual_normalized_price is not None else None,
            "absolute_cheapest_price": str(row.absolute_cheapest_price) if row.absolute_cheapest_price is not None else None,
            "recommended_price": str(row.recommended_price) if row.recommended_price is not None else None,
            "premium_amount": str(row.premium_amount) if row.premium_amount is not None else None,
            "premium_percent": str(row.premium_percent) if row.premium_percent is not None else None,
            "policy_snapshot": row.policy_snapshot,
            "actor_id": row.actor_id,
            "acknowledged_by": row.acknowledged_by,
            "acknowledged_at": row.acknowledged_at,
            "occurred_at": row.occurred_at,
        }
        for row in rows
    ]


@router.post("/deviations")
async def create_deviation(
    payload: DeviationCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: Utente = Depends(get_current_user),
):
    scope = _scope_location(user, payload.location_id)
    existing = await db.scalar(
        select(PurchasePolicyDeviation).where(
            PurchasePolicyDeviation.dedupe_key == payload.dedupe_key
        )
    )
    if existing:
        return {"id": str(existing.id), "created": False}
    await _validate_entities(
        db,
        product_id=payload.product_id,
        supplier_id=payload.selected_supplier_id,
        location_id=scope,
    )
    row = PurchasePolicyDeviation(
        dedupe_key=payload.dedupe_key,
        invoice_line_id=payload.invoice_line_id,
        purchase_order_id=payload.purchase_order_id,
        product_id=payload.product_id,
        location_id=scope,
        recommended_supplier_id=payload.recommended_supplier_id,
        selected_supplier_id=payload.selected_supplier_id,
        actual_supplier_id=payload.selected_supplier_id,
        absolute_cheapest_supplier_id=payload.absolute_cheapest_supplier_id,
        deviation_type=payload.deviation_type,
        status="open",
        actual_normalized_price=payload.actual_normalized_price,
        absolute_cheapest_price=payload.absolute_cheapest_price,
        recommended_price=payload.recommended_price,
        premium_amount=payload.premium_amount,
        premium_percent=payload.premium_percent,
        policy_snapshot=payload.policy_snapshot,
        reason=payload.reason,
        context=payload.context,
        actor_id=user.id,
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.flush()
    return {"id": str(row.id), "created": True}


@router.patch("/deviations/{deviation_id}")
async def update_deviation(
    deviation_id: UUID,
    payload: DeviationUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: Utente = Depends(get_current_user),
):
    row = await db.scalar(
        select(PurchasePolicyDeviation)
        .where(PurchasePolicyDeviation.id == deviation_id)
        .with_for_update()
    )
    if not row:
        raise HTTPException(404, "Deviazione non trovata")
    _scope_location(user, row.location_id)
    now = datetime.now(timezone.utc)
    row.status = payload.status
    if payload.reason:
        row.reason = payload.reason.strip()
    row.acknowledged_by = user.id
    row.acknowledged_at = now
    await db.flush()
    return {
        "id": str(row.id),
        "status": row.status,
        "reason": row.reason,
        "acknowledged_by": row.acknowledged_by,
        "acknowledged_at": row.acknowledged_at,
    }
