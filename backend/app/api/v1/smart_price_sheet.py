"""Smart Price Sheet, supplier assessments and purchase policy API."""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.api.deps import get_current_user, require_admin
from app.database import get_db
from app.models.fatture import Fattura, RigaFattura
from app.models.categories import MasterCategory
from app.models.fornitori import Fornitore
from app.models.listino import ListinoMaster
from app.models.location import Location
from app.models.products import Product, SupplierProductAlias
from app.models.purchase_policy import (
    ProductPurchasePolicy,
    ProductPurchasePolicyAudit,
    ProductSupplierAssessment,
    ProductSupplierAssessmentAudit,
    PurchasePolicyDeviation,
    SupplierCategoryCapability,
)
from app.models.utenti import Utente
from app.schemas.smart_price_sheet import (
    AssessmentUpsertRequest,
    CellPreviewRequest,
    ClipboardPreviewRequest,
    GoogleSheetDryRunRequest,
    NormalizedSheetDryRunRequest,
    CommitPreviewRequest,
    DeviationCreateRequest,
    DeviationUpdateRequest,
    PolicyUpsertRequest,
    SupplierSectorUpdateRequest,
    VariantPricePreviewRequest,
)
from app.services.purchase_recommendation import (
    comparable_listino_price,
    policy_snapshot,
    rank_offers_keeping_incomparable,
    rank_supplier_offers,
)
from app.services.smart_price_sheet import build_price_preview, commit_price_preview
from app.services.smart_price_export import build_matrix_workbook
from app.services.variant_price_import import build_variant_preview
from app.services.sheet_sync_dry_run import stage_snapshot
from app.services.normalized_price_workbook import parse_normalized_price_workbook, parse_normalized_sheet_values
from app.services.supplier_catalog_scope import load_supplier_catalog_scope
from app.services.matching import normalize_price_for_comparison
from app.services.smart_price_spot import SpotLine, compute_spot_offers, spot_lines_query
from app.services.smart_price_purchases import (
    PERIOD_OPTIONS,
    SORT_OPTIONS,
    STAT_COLUMNS,
    load_purchase_stats_select,
    matrix_page_select,
    period_start,
    stats_payload,
)


router = APIRouter()


def _scope_location(user: Utente, requested: int | None) -> int | None:
    ruolo_str = getattr(user.ruolo, "value", str(user.ruolo))
    if ruolo_str == "manager":
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
    subcategory: str | None = Query(default=None, max_length=100),
    location_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    sort: str = Query(default="nome", pattern="^(" + "|".join(SORT_OPTIONS) + ")$"),
    periodo: str = Query(default="tutto", pattern="^(" + "|".join(PERIOD_OPTIONS) + ")$"),
    db: AsyncSession = Depends(get_db),
    user: Utente = Depends(get_current_user),
):
    scope = _scope_location(user, location_id)
    purchases_from = period_start(periodo, date.today())
    product_filter = [Product.is_active.is_(True)]
    if search:
        term = f"%{search.strip()}%"
        product_filter.append(
            or_(
                Product.canonical_name.ilike(term),
                Product.order_name.ilike(term),
                Product.sku_interno.ilike(term),
            )
        )
    if category and category != "all" and category.strip():
        product_filter.append(func.lower(func.btrim(Product.category)) == category.strip().casefold())
    if subcategory and subcategory != "all" and subcategory.strip():
        product_filter.append(func.lower(func.btrim(Product.subcategory)) == subcategory.strip().casefold())
    total = await db.scalar(
        select(func.count()).select_from(Product).where(*product_filter)
    )
    # Acquisti, spesa, ultimo acquisto e quantita' per voce (services.smart_price_purchases):
    # con sort=acquisti/spesa/quantita l'ordinamento avviene prima di limit/offset.
    purchase_stats: dict[str, dict] = {}
    if sort == "nome":
        products = (
            await db.scalars(matrix_page_select(product_filter, sort).limit(limit).offset(offset))
        ).all()
        units = {row.sku_interno: row.comparison_unit for row in products if row.sku_interno}
        if units:
            stats_select = await load_purchase_stats_select(
                db, user, skus=list(units), location_id=scope, date_from=purchases_from
            )
            for stat in (await db.execute(stats_select)).all():
                purchase_stats[stat.sku_interno] = stats_payload(
                    *(getattr(stat, name) for name in STAT_COLUMNS), units.get(stat.sku_interno)
                )
    else:
        stats_subquery = (
            await load_purchase_stats_select(db, user, location_id=scope, date_from=purchases_from)
        ).subquery("acquisti_voce")
        page = (await db.execute(
            matrix_page_select(product_filter, sort, stats_subquery).limit(limit).offset(offset)
        )).all()
        products = [item[0] for item in page]
        for product_row, *values in page:
            if product_row.sku_interno:
                purchase_stats[product_row.sku_interno] = stats_payload(*values, product_row.comparison_unit)
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
    supplier_scope = await load_supplier_catalog_scope(
        db, supplier_ids=set(supplier_ids)
    )
    today = date.today()

    active_prices = []
    spot_prices: dict[tuple[str, int], dict] = {}
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
        # Spot = ultimo prezzo fatturato per sede, convertito nell'unità di
        # confronto (services.smart_price_spot). Righe dalla base comune: niente
        # note di credito, omaggi, righe/SKU esclusi; tenant e sede filtrati.
        spot_rows = (await db.execute(
            spot_lines_query(user, skus=skus, supplier_ids=supplier_ids, location_id=scope)
        )).all()
        spot_aliases = (
            await db.scalars(
                select(SupplierProductAlias).options(noload("*")).where(
                    SupplierProductAlias.product_id.in_(product_ids),
                    SupplierProductAlias.supplier_id.in_(supplier_ids),
                    SupplierProductAlias.status == "approved",
                )
            )
        ).all()
        spot_prices = compute_spot_offers(
            (SpotLine(*row) for row in spot_rows),
            {product.sku_interno: product for product in products if product.sku_interno},
            spot_aliases,
            today,
        )
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

    aliases_by_id = {}
    variant_alias_ids = {row.supplier_product_alias_id for row in active_prices if row.supplier_product_alias_id}
    if variant_alias_ids:
        aliases_by_id = {alias.id: alias for alias in (await db.scalars(
            select(SupplierProductAlias).options(noload("*")).where(SupplierProductAlias.id.in_(variant_alias_ids))
        )).all()}
    products_by_sku = {product.sku_interno: product for product in products if product.sku_interno}
    variant_offers_by_sku: dict[str, list[dict]] = {}
    for row in active_prices:
        alias = aliases_by_id.get(row.supplier_product_alias_id)
        product = products_by_sku.get(row.sku_interno)
        if not alias or alias.source != "normalized_sheet_offer" or not product:
            continue
        normalized = normalize_price_for_comparison(
            row.prezzo_pattuito, Decimal("1"), row.unita_misura, product, alias,
        )
        variant_offers_by_sku.setdefault(row.sku_interno, []).append({
            "offer_id": alias.supplier_code, "supplier_id": row.fornitore_id,
            "supplier_name": next((s.nome_azienda for s in suppliers if s.id == row.fornitore_id), ""),
            "description": alias.raw_description, "brand": alias.brand,
            "pack_qty": alias.pack_qty, "volume_ml": alias.volume_ml, "weight_g": alias.weight_g,
            "price": f"{Decimal(str(row.prezzo_pattuito)):.4f}",
            "comparison_price": f"{normalized.normalized_unit_price:.4f}" if normalized.reliable and row.unita_misura else None,
            "comparison_unit": normalized.comparison_unit if normalized.reliable and row.unita_misura else None,
        })

    variant_pairs = {(sku, offer["supplier_id"]) for sku, variants in variant_offers_by_sku.items() for offer in variants}
    prices: dict[tuple[str, int], dict] = {}
    for (sku, supplier_id), spot_offer in spot_prices.items():
        if (sku, supplier_id) in variant_pairs:
            continue
        prices[(sku, supplier_id)] = spot_offer
    for row in active_prices:
        key = (row.sku_interno, row.fornitore_id)
        if key in variant_pairs:
            alias = aliases_by_id.get(row.supplier_product_alias_id)
            if not alias or alias.source != "normalized_sheet_offer":
                continue
            variant = next((offer for offer in variant_offers_by_sku[row.sku_interno] if offer["offer_id"] == alias.supplier_code), None)
            if not variant or variant["comparison_price"] is None:
                continue
            previous = prices.get(key)
            if (
                previous
                and previous.get("unit_price_normalized") is not None
                and Decimal(previous["unit_price_normalized"]) <= Decimal(variant["comparison_price"])
            ):
                continue
            prices[key] = {
                "supplier_id": row.fornitore_id,
                "unit_price_normalized": variant["comparison_price"],
                "price": variant["price"],
                "source_type": "contratto", "uom": "conf",
                "offer_id": variant["offer_id"],
            }
            continue
        if key in prices and prices[key].get("source_type") == "contratto":
            continue
        # Prezzo nell'unità di confronto della voce; None se non confrontabile
        # (senza unità o conversione incerta): l'offerta resta visibile ma fuori classifica.
        comparable = comparable_listino_price(
            row, products_by_sku.get(row.sku_interno), aliases_by_id.get(row.supplier_product_alias_id),
        )
        prices[key] = {
            "supplier_id": row.fornitore_id,
            "unit_price_normalized": f"{comparable:.4f}" if comparable is not None else None,
            "comparison_reliable": comparable is not None,
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
        eligible_supplier_ids = supplier_scope.eligible_supplier_ids(
            product_id=product.id,
            category=product.category,
            subcategory=product.subcategory,
            supplier_ids=set(supplier_ids),
        )
        offers = []
        if product.sku_interno:
            for supplier in suppliers:
                offer = prices.get((product.sku_interno, supplier.id))
                if offer:
                    offers.append({**offer, "supplier_name": supplier.nome_azienda})
        recommendation = rank_offers_keeping_incomparable(
            offers,
            effective_assessments.get(product.id, {}),
            effective_policies.get(product.id),
        )
        rows.append(
            {
                "product_id": product.id,
                "sku_interno": product.sku_interno,
                "canonical_name": product.canonical_name,
                "order_name": product.order_name,
                "category": product.category,
                "subcategory": product.subcategory,
                "comparison_unit": product.comparison_unit,
                **purchase_stats.get(
                    product.sku_interno or "", stats_payload(0, 0, None, comparison_unit=product.comparison_unit)
                ),
                "offers": {str(item["supplier_id"]): item for item in recommendation["offers"]},
                "variant_offers": variant_offers_by_sku.get(product.sku_interno, []),
                "eligible_supplier_ids": sorted(eligible_supplier_ids),
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
    category_counts_res = await db.execute(
        select(Product.category, func.count(Product.id))
        .where(Product.is_active.is_(True))
        .group_by(Product.category)
    )
    category_counts = {str(cat): count for cat, count in category_counts_res.all() if cat}

    subcategory_counts_stmt = select(
        Product.subcategory, func.count(Product.id)
    ).where(Product.is_active.is_(True), Product.subcategory.is_not(None))
    if category and category != "all" and category.strip():
        subcategory_counts_stmt = subcategory_counts_stmt.where(
            func.lower(func.btrim(Product.category)) == category.strip().casefold()
        )
    subcategory_counts_stmt = subcategory_counts_stmt.group_by(Product.subcategory)
    subcategory_counts_res = await db.execute(subcategory_counts_stmt)
    subcategory_counts = {str(sub): count for sub, count in subcategory_counts_res.all() if sub}

    filtered_suppliers = suppliers
    if category:
        norm_cat = category.strip().casefold()
        norm_sub = subcategory.strip().casefold() if subcategory and subcategory != "all" and subcategory.strip() else None

        eligible_supplier_ids_for_cat = set()
        for s in suppliers:
            # 1. Check if category is explicitly disabled
            explicit_cat = supplier_scope.explicit_categories.get((s.id, norm_cat))
            if explicit_cat is False:
                continue

            # 2. If subcategory is specified, check subcategory eligibility
            if norm_sub:
                enabled_subs = (
                    supplier_scope.subcategories_by_supplier_category.get((s.id, norm_cat), set())
                    if supplier_scope.subcategories_by_supplier_category
                    else set()
                )
                is_eligible = (
                    norm_sub in enabled_subs
                    or any(s.id in r["eligible_supplier_ids"] for r in rows)
                )
            else:
                is_eligible = (
                    explicit_cat is True
                    or (explicit_cat is not False and norm_cat in supplier_scope.categories_by_supplier.get(s.id, set()))
                    or any(s.id in r["eligible_supplier_ids"] for r in rows)
                )

            if is_eligible:
                eligible_supplier_ids_for_cat.add(s.id)

        # Fallback if no specific suppliers configured for this category (only when no specific subcategory is requested)
        if not eligible_supplier_ids_for_cat and not norm_sub:
            eligible_supplier_ids_for_cat = {
                s.id for s in suppliers
                if supplier_scope.explicit_categories.get((s.id, norm_cat)) is not False
            }

        filtered_suppliers = [s for s in suppliers if s.id in eligible_supplier_ids_for_cat]

    return {
        "total": total or 0,
        "limit": limit,
        "offset": offset,
        "location_id": scope,
        "sort": sort,
        "periodo": periodo,
        "category_counts": category_counts,
        "subcategory_counts": subcategory_counts,
        "suppliers": [
            {"id": row.id, "name": row.nome_azienda, "vat": row.partita_iva}
            for row in filtered_suppliers
        ],
        "supplier_names": [s.nome_azienda for s in filtered_suppliers],
        "rows": rows,
    }


@router.get("/matrix/export")
async def matrix_export(
    search: str | None = Query(default=None, max_length=150),
    category: str | None = Query(default=None, max_length=100),
    subcategory: str | None = Query(default=None, max_length=100),
    location_id: int | None = Query(default=None, gt=0),
    sort: str = Query(default="nome", pattern="^(" + "|".join(SORT_OPTIONS) + ")$"),
    periodo: str = Query(default="tutto", pattern="^(" + "|".join(PERIOD_OPTIONS) + ")$"),
    db: AsyncSession = Depends(get_db),
    user: Utente = Depends(get_current_user),
):
    """Tutte le righe della matrice con i filtri della schermata, in un file Excel."""
    rows: list[dict] = []
    suppliers: list[dict] = []
    offset = 0
    while True:
        page = await matrix(
            search=search, category=category, subcategory=subcategory, location_id=location_id,
            limit=500, offset=offset, sort=sort, periodo=periodo, db=db, user=user,
        )
        rows.extend(page["rows"])
        suppliers.extend(page["suppliers"])
        offset += 500
        if not page["rows"] or offset >= page["total"]:
            break
    title = " - ".join(part for part in (category if category and category != "all" else "Tutte",
                                         subcategory if subcategory and subcategory != "all" else None) if part)
    content = await run_in_threadpool(build_matrix_workbook, rows, suppliers, title)
    slug = "".join(ch if ch.isalnum() else "_" for ch in title).strip("_").lower() or "listino"
    filename = f"listino_smart_{slug}_{date.today():%Y-%m-%d}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _load_all_categories(db: AsyncSession) -> list[str]:
    # 1. Master categories Ho.Re.Ca.
    master_cats = (
        await db.scalars(
            select(MasterCategory.nome)
            .where(MasterCategory.is_active.is_(True))
            .order_by(MasterCategory.nome)
        )
    ).all()

    # 2. Product categories
    prod_cats = (
        await db.scalars(
            select(Product.category)
            .where(
                Product.is_active.is_(True),
                Product.category.is_not(None),
                func.length(func.btrim(Product.category)) > 0,
            )
            .distinct()
        )
    ).all()

    # 3. Supplier capability categories
    cap_cats = (
        await db.scalars(
            select(SupplierCategoryCapability.category)
            .where(
                SupplierCategoryCapability.category.is_not(None),
                func.length(func.btrim(SupplierCategoryCapability.category)) > 0,
            )
            .distinct()
        )
    ).all()

    seen = {}
    for c in list(master_cats) + list(prod_cats) + list(cap_cats):
        if c and c.strip():
            k = c.strip().casefold()
            if k not in seen:
                seen[k] = c.strip()
    return sorted(seen.values())


@router.get("/supplier-sectors")
async def supplier_sectors(
    db: AsyncSession = Depends(get_db),
    _: Utente = Depends(require_admin),
):
    suppliers = (
        await db.scalars(
            select(Fornitore)
            .options(noload("*"))
            .where(Fornitore.attivo_whitelist.is_(True))
            .order_by(Fornitore.nome_azienda, Fornitore.id)
        )
    ).all()
    categories = await _load_all_categories(db)
    scope = await load_supplier_catalog_scope(
        db, supplier_ids={supplier.id for supplier in suppliers}
    )
    return {
        "categories": categories,
        "suppliers": [
            {
                "id": supplier.id,
                "name": supplier.nome_azienda,
                "sectors": [
                    {
                        "category": category,
                        "mode": (
                            "auto"
                            if (supplier.id, category.strip().casefold())
                            not in scope.explicit_categories
                            else (
                                "enabled"
                                if scope.explicit_categories[
                                    (supplier.id, category.strip().casefold())
                                ]
                                else "disabled"
                            )
                        ),
                        "inferred": category.strip().casefold()
                        in scope.categories_by_supplier.get(supplier.id, set()),
                        "effective_enabled": supplier.id
                        in scope.eligible_supplier_ids(
                            product_id=-1,
                            category=category,
                            supplier_ids={supplier.id},
                        ),
                    }
                    for category in categories
                ],
            }
            for supplier in suppliers
        ],
    }


@router.put("/supplier-sectors")
async def update_supplier_sector(
    payload: SupplierSectorUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: Utente = Depends(require_admin),
):
    supplier = await db.scalar(
        select(Fornitore)
        .options(noload("*"))
        .where(Fornitore.id == payload.supplier_id)
    )
    if not supplier:
        raise HTTPException(404, "Fornitore non trovato")
    categories = await _load_all_categories(db)
    category_by_key = {
        category.strip().casefold(): category.strip()
        for category in categories
        if category and category.strip()
    }
    category = category_by_key.get(payload.category.strip().casefold())
    if not category:
        category = payload.category.strip()
    capability = await db.scalar(
        select(SupplierCategoryCapability).where(
            SupplierCategoryCapability.supplier_id == supplier.id,
            func.lower(func.btrim(SupplierCategoryCapability.category))
            == category.casefold(),
        )
    )
    now = datetime.now(timezone.utc)
    if payload.mode == "auto":
        if capability:
            await db.delete(capability)
    elif capability:
        capability.category = category
        capability.enabled = payload.mode == "enabled"
        capability.reason = payload.reason.strip() if payload.reason else None
        capability.updated_by = user.id
        capability.updated_at = now
    else:
        capability = SupplierCategoryCapability(
            supplier_id=supplier.id,
            category=category,
            enabled=payload.mode == "enabled",
            reason=payload.reason.strip() if payload.reason else None,
            created_by=user.id,
            updated_by=user.id,
            created_at=now,
            updated_at=now,
        )
        db.add(capability)
    await db.flush()
    return {
        "supplier_id": supplier.id,
        "supplier_name": supplier.nome_azienda,
        "category": category,
        "mode": payload.mode,
    }


@router.post("/google-dry-run")
async def google_sheet_dry_run(
    payload: GoogleSheetDryRunRequest,
    user: Utente = Depends(require_admin),
):
    """Read-only staging report. It deliberately has no database dependency."""
    if payload.title.strip().casefold() != "santo graal":
        raise HTTPException(422, "Il file sorgente deve chiamarsi “santo graal”")
    report = stage_snapshot(
        payload.values,
        spreadsheet_id=payload.spreadsheet_id,
        dynamic_supplier_headers=payload.dynamic_supplier_headers,
    )
    report["workbook_title"] = payload.title.strip()
    return report


@router.post("/normalized-google-dry-run")
async def normalized_google_dry_run(
    payload: NormalizedSheetDryRunRequest,
    user: Utente = Depends(require_admin),
):
    """Read-only preview of the normalized Google Sheet."""
    try:
        return parse_normalized_sheet_values(payload.values, payload.spreadsheet_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/excel-dry-run")
async def normalized_excel_dry_run(
    file: UploadFile = File(..., description="Workbook migrato PRICE SENTINEL .xlsx"),
    user: Utente = Depends(require_admin),
):
    """Read-only preview for the normalized category workbook; never writes to Sheets or contracts."""
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(400, "Formato non supportato. Seleziona il file Excel .xlsx migrato.")
    raw = await file.read()
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "Il file Excel è vuoto o supera il limite di 10 MB.")
    try:
        report = parse_normalized_price_workbook(raw)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return report


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
            allow_missing_uom=payload.allow_missing_uom,
            create_missing_products=payload.create_missing_products,
            category=payload.category,
            subcategory=payload.subcategory,
            location_id=scope,
            actor_id=user.id,
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return _preview_response(preview)


@router.post("/variant-preview")
async def preview_variants(
    payload: VariantPricePreviewRequest,
    db: AsyncSession = Depends(get_db),
    user: Utente = Depends(require_admin),
):
    """Preview separate package offers without collapsing supplier/product pairs."""
    preview = await build_variant_preview(db, payload, user.id)
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
    # The unit chosen in the cell editor is part of the row: without the unit
    # column the product's comparison unit would silently replace it
    # (19,67 / CT saved as 19,67 / Pz).
    cell_uom = " ".join(payload.uom.split())
    text_value = (
        f"Prodotto\tUnità di misura\t{supplier.nome_azienda}\n"
        f"{product.canonical_name}\t{cell_uom}\t{payload.price}"
    )
    preview = await build_price_preview(
        db,
        text_value=text_value,
        supplier_mapping={supplier.nome_azienda: supplier.id},
        product_mapping={product.canonical_name: product.id},
        effective_date=payload.effective_date,
        default_uom=cell_uom,
        allow_unit_assignment=True,
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
    preview, result = await commit_price_preview(
        db, token=payload.preview_token, actor_id=user.id
    )
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
