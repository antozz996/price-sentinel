from decimal import Decimal
from datetime import date
from typing import Optional, List
from difflib import SequenceMatcher
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
    allow_equivalent: bool = False,
    location_id: Optional[int] = None,
) -> dict:
    """
    Risolve una riga d'ordine cercandola nel catalogo interno canonico,
    trovando tutti gli alias approvati e ordinandoli per prezzo normalizzato crescente.
    """
    query_norm = normalize_text(query)
    if not query_norm:
        return {
            "query": query,
            "matched_product": None,
            "decision": "not_found",
            "best_offer": None,
            "alternatives": [],
            "warnings": ["La stringa di ricerca è vuota."]
        }

    # 1. Ricerca del prodotto canonico
    # A. Corrispondenza esatta/ilike
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
        # B. Corrispondenza fuzzy su tutti i prodotti attivi
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
            "matched_product": None,
            "decision": "not_found",
            "best_offer": None,
            "alternatives": [],
            "warnings": [f"Nessun prodotto canonico trovato per '{query}'."]
        }

    # 2. Risoluzione degli ID di prodotto da includere
    product_ids = [matched_product.id]
    if allow_equivalent:
        # Trova altri prodotti nello stesso gruppo di equivalenza
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

    # 3. Carica gli alias approvati del fornitore per questi prodotti
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

        # Cerca prezzo contrattuale attivo in ListinoMaster
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
            # Fallback su prezzo storico delle fatture (spot)
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
            invoice_uom=prod.comparison_unit,
            product=prod,
            alias=alias
        )

        if not norm_res.reliable:
            warnings.append(
                f"Impossibile normalizzare il prezzo per {supplier.nome_azienda}: {norm_res.explanation}"
            )
            continue

        # Calcola totale stimato dell'offerta
        # Se la comparison_unit è piece/bottle, consideriamo che ordiniamo in confezioni da 'pack_qty' pezzi.
        # Il totale stimato è quindi: prezzo_confezione * requested_qty
        estimated_total = price_val * Decimal(str(requested_qty))

        offers.append({
            "supplier_id": alias.supplier_id,
            "supplier_name": supplier.nome_azienda,
            "supplier_product_name": alias.raw_description,
            "supplier_code": alias.supplier_code,
            "pack_qty": norm_res.pack_qty,
            "price": f"{price_val:.4f}",
            "normalized_unit_price": f"{norm_res.normalized_unit_price:.4f}",
            "comparison_unit": norm_res.comparison_unit,
            "estimated_total": f"{estimated_total:.4f}",
            "source_type": source_type,
            "is_equivalent": prod.id != matched_product.id
        })

    # Ordina per prezzo normalizzato unitario crescente
    offers.sort(key=lambda x: Decimal(x["normalized_unit_price"]))

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
        "matched_product": {
            "product_id": matched_product.id,
            "sku_interno": matched_product.sku_interno,
            "canonical_name": matched_product.canonical_name
        },
        "decision": decision,
        "best_offer": best_offer,
        "alternatives": alternatives,
        "warnings": warnings
    }
