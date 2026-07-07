from decimal import Decimal
from datetime import date
from typing import Optional, List
from difflib import SequenceMatcher
import math
import json

from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.products import Product, SupplierProductAlias, ProductEquivalenceGroupItem
from app.models.listino import ListinoMaster
from app.services.normalization import normalize_text
from app.services.matching import normalize_price_for_comparison


async def resolve_order_item(
    db: AsyncSession,
    query: str,
    requested_qty: Decimal = Decimal("1"),
    requested_unit: Optional[str] = None,
    allow_equivalent: bool = False,
    location_id: Optional[int] = None,
) -> dict:
    """
    Risolve una riga d'ordine cercandola nel catalogo interno canonico,
    trovando tutti gli alias approvati e ordinandoli per prezzo normalizzato crescente.
    Gestisce la semantica delle quantità calcolando confezioni necessarie ed unità effettive.
    """
    query_norm = normalize_text(query)
    if not query_norm:
        return {
            "query": query,
            "requested_qty": float(requested_qty),
            "requested_unit": requested_unit,
            "matched_product": None,
            "decision": "not_found",
            "best_offer": None,
            "alternatives": [],
            "warnings": ["La stringa di ricerca è vuota."]
        }

    # 1. Ricerca del prodotto canonico
    stmt = select(Product).where(
        and_(
            Product.is_active == True,
            or_(
                Product.sku_interno == query.strip(),
                Product.sku_interno == query_norm,
                Product.normalized_name == query_norm,
                Product.canonical_name.ilike(query.strip())
            )
        )
    )
    res = await db.execute(stmt)
    matched_products = res.scalars().all()

    matched_product = None
    if matched_products:
        matched_product = matched_products[0]
    else:
        # Corrispondenza fuzzy su tutti i prodotti attivi
        stmt_all = select(Product).where(Product.is_active == True)
        res_all = await db.execute(stmt_all)
        all_products = res_all.scalars().all()
        best_score = 0.0
        for p in all_products:
            score_canon = SequenceMatcher(None, query_norm, normalize_text(p.canonical_name)).ratio()
            score_sku = SequenceMatcher(None, query_norm, normalize_text(p.sku_interno or "")).ratio()
            score = max(score_canon, score_sku)
            if score > 0.70 and score > best_score:
                best_score = score
                matched_product = p

    if not matched_product:
        return {
            "query": query,
            "requested_qty": float(requested_qty),
            "requested_unit": requested_unit,
            "matched_product": None,
            "decision": "not_found",
            "best_offer": None,
            "alternatives": [],
            "warnings": [f"Nessun prodotto canonico trovato per '{query}'."]
        }

    comp_unit = matched_product.comparison_unit
    unit_count = matched_product.unit_count or 1
    volume_ml = matched_product.volume_ml or 0
    weight_g = matched_product.weight_g or 0

    if not requested_unit:
        requested_unit = comp_unit or "piece"

    # Conversione quantità a unità di confronto target
    target_total_units = Decimal(str(requested_qty))
    
    if requested_unit == "box" and comp_unit in ("piece", "bottle"):
        target_total_units = Decimal(str(requested_qty)) * Decimal(str(unit_count))
    elif requested_unit in ("piece", "bottle") and comp_unit == "box" and unit_count > 0:
        target_total_units = Decimal(str(requested_qty)) / Decimal(str(unit_count))
    elif requested_unit in ("piece", "bottle") and comp_unit == "liter" and volume_ml > 0:
        target_total_units = Decimal(str(requested_qty)) * (Decimal(str(volume_ml)) / Decimal("1000"))
    elif requested_unit == "piece" and comp_unit == "kg" and weight_g > 0:
        target_total_units = Decimal(str(requested_qty)) * (Decimal(str(weight_g)) / Decimal("1000"))

    # 2. Risoluzione degli ID di prodotto da includere
    product_ids = [matched_product.id]
    if allow_equivalent:
        subq = select(ProductEquivalenceGroupItem.group_id).where(
            ProductEquivalenceGroupItem.product_id == matched_product.id
        )
        equiv_stmt = select(ProductEquivalenceGroupItem.product_id).where(
            ProductEquivalenceGroupItem.group_id.in_(subq)
        )
        equiv_res = await db.execute(equiv_stmt)
        equiv_ids = equiv_res.scalars().all()
        for eid in equiv_ids:
            if eid not in product_ids:
                product_ids.append(eid)

    # 3. Carica gli alias approvati per questi prodotti
    alias_stmt = (
        select(SupplierProductAlias)
        .options(
            selectinload(SupplierProductAlias.supplier),
            selectinload(SupplierProductAlias.product)
        )
        .where(
            and_(
                SupplierProductAlias.product_id.in_(product_ids),
                SupplierProductAlias.status == "approved"
            )
        )
    )
    aliases = (await db.execute(alias_stmt)).scalars().all()

    offers = []
    warnings = []
    today = date.today()

    # 4. Calcola e normalizza il prezzo per ciascun alias
    for alias in aliases:
        prod = alias.product
        supplier = alias.supplier

        # Cerca prezzo contrattuale attivo
        listino_stmt = select(ListinoMaster).where(
            and_(
                ListinoMaster.fornitore_id == alias.supplier_id,
                ListinoMaster.sku_interno == prod.sku_interno,
                ListinoMaster.data_inizio_validita <= today,
                or_(
                    ListinoMaster.data_scadenza.is_(None),
                    ListinoMaster.data_scadenza >= today
                )
            )
        ).order_by(ListinoMaster.data_inizio_validita.desc()).limit(1)

        listino_res = await db.execute(listino_stmt)
        listino = listino_res.scalar_one_or_none()

        price_val = None
        source_type = "contratto"

        if listino:
            price_val = Decimal(str(listino.prezzo_pattuito))
        else:
            # Fallback spot su fatture passate
            from app.models.fatture import RigaFattura, Fattura
            spot_stmt = (
                select(RigaFattura.prezzo_netto_normalizzato)
                .join(Fattura)
                .where(
                    and_(
                        Fattura.fornitore_id == alias.supplier_id,
                        RigaFattura.sku_interno == prod.sku_interno
                    )
                )
                .order_by(Fattura.data_documento.desc())
                .limit(1)
            )
            spot_res = await db.execute(spot_stmt)
            spot_price = spot_res.scalar()
            if spot_price is not None:
                price_val = Decimal(str(spot_price))
                source_type = "spot"

        if price_val is None:
            warnings.append(
                f"Nessuna tariffa a listino o prezzo storico per {supplier.nome_azienda} su SKU {prod.sku_interno}."
            )
            continue

        # Esegui normalizzazione prezzo
        norm_res = normalize_price_for_comparison(
            price_or_line=price_val,
            quantity_or_product=Decimal("1"),
            invoice_uom=listino.unita_misura if listino else prod.comparison_unit,
            product=prod,
            alias=alias
        )

        if not norm_res.reliable:
            warnings.append(
                f"Impossibile normalizzare il prezzo per {supplier.nome_azienda}: {norm_res.explanation}"
            )
            continue

        # Risolvi pack_qty specifico
        pack_qty = None
        if alias.pack_qty is not None:
            pack_qty = alias.pack_qty
        if pack_qty is None and prod.unit_count is not None:
            pack_qty = prod.unit_count
        if pack_qty is None or pack_qty <= 0:
            pack_qty = 1

        alias_vol = alias.volume_ml if alias.volume_ml is not None else prod.volume_ml
        alias_w = alias.weight_g if alias.weight_g is not None else prod.weight_g

        # Calcolo di packs_needed e actual_units_supplied
        if comp_unit in ("piece", "bottle"):
            packs_needed = int(math.ceil(float(target_total_units) / pack_qty))
            actual_units_supplied = packs_needed * pack_qty
        elif comp_unit == "liter" and alias_vol and alias_vol > 0:
            liters_per_pack = (pack_qty * alias_vol) / 1000.0
            packs_needed = int(math.ceil(float(target_total_units) / liters_per_pack))
            actual_units_supplied = float(packs_needed * liters_per_pack)
        elif comp_unit == "kg" and alias_w and alias_w > 0:
            kg_per_pack = (pack_qty * alias_w) / 1000.0
            packs_needed = int(math.ceil(float(target_total_units) / kg_per_pack))
            actual_units_supplied = float(packs_needed * kg_per_pack)
        else:
            packs_needed = int(math.ceil(float(target_total_units)))
            actual_units_supplied = float(packs_needed)

        # Totale stimato dell'offerta: prezzo_confezione * packs_needed
        estimated_total = price_val * Decimal(str(packs_needed))

        offers.append({
            "supplier_id": alias.supplier_id,
            "supplier_name": supplier.nome_azienda,
            "supplier_product_name": alias.raw_description,
            "supplier_code": alias.supplier_code,
            "pack_qty": pack_qty,
            "packs_needed": packs_needed,
            "actual_units_supplied": actual_units_supplied,
            "price_per_pack": f"{price_val:.4f}",
            "unit_price_normalized": f"{norm_res.normalized_unit_price:.4f}",
            "comparison_unit": norm_res.comparison_unit,
            "estimated_total": f"{estimated_total:.4f}",
            "source_type": source_type,
            "is_equivalent": prod.id != matched_product.id
        })

    # Ordina per prezzo unitario normalizzato crescente
    offers.sort(key=lambda x: Decimal(x["unit_price_normalized"]))

    if offers:
        best_offer = offers[0]
        alternatives = offers[1:]
        decision = "resolved"
    else:
        best_offer = None
        alternatives = []
        decision = "needs_review"
        warnings.append("Nessun fornitore disponibile con tariffe valide.")

    return {
        "query": query,
        "requested_qty": float(requested_qty),
        "requested_unit": requested_unit,
        "matched_product": {
            "sku_interno": matched_product.sku_interno,
            "canonical_name": matched_product.canonical_name,
            "comparison_unit": comp_unit
        },
        "decision": decision,
        "best_offer": best_offer,
        "alternatives": alternatives,
        "warnings": warnings
    }
