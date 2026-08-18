"""Safe clipboard preview and idempotent append-only price commit helpers."""

import csv
import hashlib
import io
import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.models.fornitori import Fornitore
from app.models.listino import ListinoMaster
from app.models.products import Product, SupplierProductAlias
from app.models.purchase_policy import SmartPriceSheetPreview
from app.services.normalization import infer_category, normalize_text
from app.services.supplier_catalog_scope import load_supplier_catalog_scope


MAX_ROWS = 5000
MAX_SUPPLIERS = 100


def parse_decimal_price(raw: object) -> Decimal | None:
    raw_str = str(raw or "").strip().replace("€", "").strip()
    value = raw_str.rstrip(",;.- ").strip().replace(" ", "")
    if not value:
        return None
    val_lower = value.lower()
    if val_lower in {
        "-", "--", "---", "/", "//", "n/a", "na", "nd", "n.d.", "n/d", 
        "no", "non", "none", "null", "assente", "non disponibile", "non trattato",
        "fuori assortimento", "non a listino", "x", "xx", "xxx", "zero",
        "0", "0.0", "0,0", "0.00", "0,00", "0.000", "0,000", "0.0000", "0,0000"
    }:
        return None
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        value = value.replace(",", ".")
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return None
    if parsed <= 0:
        return None
    if parsed >= Decimal("100000000"):
        raise ValueError(f"Prezzo fuori intervallo: {raw}")
    if parsed.as_tuple().exponent < -4:
        parsed = parsed.quantize(Decimal("0.0001"))
    return parsed


def parse_clipboard_table(text_value: str) -> dict:
    text_value = text_value.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if not text_value.strip():
        raise ValueError("Il contenuto incollato è vuoto")
    first_line = text_value.split("\n", 1)[0]
    if "\t" in first_line:
        delimiter = "\t"
    else:
        try:
            delimiter = csv.Sniffer().sniff(first_line, delimiters=";,|").delimiter
        except csv.Error:
            delimiter = ";"
    rows = [
        [cell.strip() for cell in row]
        for row in csv.reader(io.StringIO(text_value), delimiter=delimiter)
        if any(cell.strip() for cell in row)
    ]
    first_header = normalize_text(rows[0][0]) if rows and rows[0] else ""
    has_order_name = first_header.startswith("nome rapido") or first_header in {
        "nome ordine",
        "nome semplice",
        "order name",
    }
    product_column = 1 if has_order_name else 0
    
    # Riconoscimento colonna Unità di Misura (UoM) per singolo prodotto
    next_col_index = product_column + 1
    has_uom_column = False
    if len(rows[0]) > next_col_index:
        next_header = normalize_text(rows[0][next_col_index])
        if next_header in {"unita di misura", "unita", "uom", "unit", "unita misura", "udm"}:
            has_uom_column = True

    supplier_start = (next_col_index + 1) if has_uom_column else next_col_index
    minimum_columns = supplier_start + 1
    if len(rows) < 2 or len(rows[0]) < minimum_columns:
        raise ValueError("Servono una riga intestazioni, il prodotto e almeno una colonna fornitore")
    if len(rows) - 1 > MAX_ROWS:
        raise ValueError(f"Massimo {MAX_ROWS} prodotti per operazione")
    if len(rows[0]) - supplier_start > MAX_SUPPLIERS:
        raise ValueError(f"Massimo {MAX_SUPPLIERS} fornitori per operazione")
    width = len(rows[0])
    normalized_rows = [row + [""] * (width - len(row)) for row in rows[1:]]
    if any(len(row) > width for row in normalized_rows):
        raise ValueError("Una o più righe hanno più colonne dell'intestazione")
    supplier_headers = rows[0][supplier_start:]
    if any(not header for header in supplier_headers):
        raise ValueError("Le intestazioni fornitore non possono essere vuote")
    if len({normalize_text(item) for item in supplier_headers}) != len(supplier_headers):
        raise ValueError("Le intestazioni fornitore devono essere univoche")
    return {
        "delimiter": "tab" if delimiter == "\t" else delimiter,
        "order_name_header": rows[0][0] if has_order_name else None,
        "product_header": rows[0][product_column] or "Prodotto",
        "uom_header": rows[0][next_col_index] if has_uom_column else None,
        "supplier_headers": supplier_headers,
        "rows": [
            {
                "row_number": index + 2,
                "order_name": row[0] if has_order_name else "",
                "product_ref": row[product_column],
                "uom": (row[next_col_index].strip() if has_uom_column and len(row) > next_col_index else "") or "",
                "values": row[supplier_start:width],
            }
            for index, row in enumerate(normalized_rows)
        ],
    }


def _price_string(value: Decimal | None) -> str | None:
    return f"{value:.4f}" if value is not None else None


async def build_price_preview(
    db: AsyncSession,
    *,
    text_value: str,
    supplier_mapping: dict[str, int],
    product_mapping: dict[str, int],
    effective_date: date,
    default_uom: str,
    create_missing_products: bool = True,
    category: str | None = None,
    location_id: int | None,
    actor_id: int,
) -> SmartPriceSheetPreview:
    parsed = parse_clipboard_table(text_value)
    suppliers = (
        await db.scalars(
            select(Fornitore).options(noload("*")).order_by(Fornitore.id)
        )
    ).all()
    supplier_by_id = {row.id: row for row in suppliers}
    supplier_by_name: dict[str, list[Fornitore]] = defaultdict(list)
    for row in suppliers:
        supplier_by_name[normalize_text(row.nome_azienda)].append(row)
        supplier_by_name[normalize_text(row.partita_iva)].append(row)

    resolved_suppliers: dict[str, Fornitore] = {}
    mapping_report: list[dict] = []
    errors: list[dict] = []
    for header in parsed["supplier_headers"]:
        explicit_id = supplier_mapping.get(header)
        if explicit_id is not None and explicit_id > 0:
            supplier = supplier_by_id.get(explicit_id)
            method = "explicit"
        elif explicit_id == -1:
            # Forzatura esplicita per creazione fornitore provvisorio
            supplier = None
            method = "auto_create"
        else:
            matches = supplier_by_name.get(normalize_text(header), [])
            if not matches:
                compact_header = "".join(
                    character
                    for character in normalize_text(header)
                    if character.isalnum()
                )
                if len(compact_header) >= 3:
                    matches = [
                        candidate
                        for candidate in suppliers
                        if compact_header
                        in "".join(
                            character
                            for character in normalize_text(candidate.nome_azienda)
                            if character.isalnum()
                        )
                    ]
            supplier = matches[0] if len(matches) == 1 else None
            method = (
                "exact_name"
                if supplier and supplier_by_name.get(normalize_text(header))
                else "unique_short_name" if supplier else "unresolved"
            )
        if not supplier:
            if create_missing_products or explicit_id == -1:
                norm_header = normalize_text(header)
                temp_piva = f"TEMP{hashlib.sha256(norm_header.encode('utf-8')).hexdigest()[:7].upper()}"
                supplier = Fornitore(
                    nome_azienda=header.strip(),
                    partita_iva=temp_piva,
                    attivo_whitelist=True,
                )
                method = "auto_create"
                resolved_suppliers[header] = supplier
            else:
                errors.append(
                    {
                        "type": "supplier_mapping",
                        "header": header,
                        "message": "Fornitore non trovato o ambiguo: selezionalo esplicitamente o crealo come nuovo fornitore.",
                    }
                )
        else:
            resolved_suppliers[header] = supplier
        mapping_report.append(
            {
                "header": header,
                "supplier_id": supplier.id if getattr(supplier, "id", None) else None,
                "supplier_name": supplier.nome_azienda if supplier else None,
                "method": method,
            }
        )

    products = (
        await db.scalars(select(Product).where(Product.is_active.is_(True)).order_by(Product.id))
    ).all()
    product_by_id = {row.id: row for row in products}
    product_candidates: dict[str, list[Product]] = defaultdict(list)
    invoice_alias_candidates: dict[str, list[Product]] = defaultdict(list)
    order_name_candidates: dict[str, list[Product]] = defaultdict(list)
    for row in products:
        for value in {row.sku_interno, row.canonical_name, row.normalized_name}:
            if value:
                product_candidates[normalize_text(value)].append(row)
        if row.normalized_order_name:
            order_name_candidates[row.normalized_order_name].append(row)
    catalog_aliases = (
        await db.scalars(
            select(SupplierProductAlias)
            .options(noload("*"))
            .where(SupplierProductAlias.status == "approved")
            .order_by(SupplierProductAlias.id)
        )
    ).all()
    for alias in catalog_aliases:
        product = product_by_id.get(alias.product_id)
        if not product:
            continue
        for value in {
            alias.raw_description,
            alias.normalized_description,
            alias.supplier_code,
        }:
            if value:
                invoice_alias_candidates[normalize_text(value)].append(product)

    resolved_rows: list[tuple[dict, Product, str]] = []
    product_report: list[dict] = []
    for source_row in parsed["rows"]:
        ref = source_row["product_ref"]
        explicit_id = product_mapping.get(ref)
        if explicit_id is not None:
            product = product_by_id.get(explicit_id)
            method = "explicit"
        else:
            unique = {item.id: item for item in product_candidates.get(normalize_text(ref), []) if item.id}
            method = "exact_catalog"
            if not unique:
                unique = {
                    item.id: item
                    for item in invoice_alias_candidates.get(normalize_text(ref), [])
                    if item.id
                }
                method = "exact_invoice_alias"
            if not unique:
                unique = {
                    item.id: item
                    for item in order_name_candidates.get(normalize_text(ref), [])
                    if item.id
                }
                method = "exact_order_name"
            product = next(iter(unique.values())) if len(unique) == 1 else None
            method = method if product else "unresolved"
        if not product:
            if create_missing_products and ref.strip():
                norm_ref = normalize_text(ref)
                virtual_sku = f"IMP-{hashlib.sha256(norm_ref.encode('utf-8')).hexdigest()[:10].upper()}"
                row_uom = source_row.get("uom", "").strip() or default_uom or "Pz"
                product = Product(
                    sku_interno=virtual_sku,
                    canonical_name=ref.strip(),
                    normalized_name=norm_ref,
                    category=category or infer_category(ref) or "Beverage",
                    comparison_unit=row_uom,
                    is_active=True,
                )
                method = "auto_create"
                product_candidates[norm_ref].append(product)
                resolved_rows.append((source_row, product, method))
            else:
                errors.append(
                    {
                        "type": "product_mapping",
                        "row": source_row["row_number"],
                        "reference": ref,
                        "message": "Descrizione mai vista o ambigua: scegli il prodotto principale una sola volta.",
                    }
                )
        elif not product.sku_interno:
            errors.append(
                {
                    "type": "missing_sku",
                    "row": source_row["row_number"],
                    "reference": ref,
                    "message": "Il prodotto canonico non ha uno SKU interno: completare prima il catalogo.",
                }
            )
        else:
            resolved_rows.append((source_row, product, method))
        product_report.append(
            {
                "row": source_row["row_number"],
                "reference": ref,
                "product_id": product.id if getattr(product, 'id', None) else None,
                "sku_interno": product.sku_interno if product else None,
                "canonical_name": product.canonical_name if product else None,
                "order_name": product.order_name if product else None,
                "method": method,
            }
        )

    order_name_changes_by_product: dict[str, dict] = {}
    proposed_name_owners: dict[str, str] = {}
    existing_name_owners = {
        row.normalized_order_name: str(row.id)
        for row in products
        if row.normalized_order_name
    }
    for source_row, product, _ in resolved_rows:
        proposed = source_row.get("order_name", "").strip()
        if not proposed:
            continue
        if len(proposed) > 120:
            errors.append(
                {
                    "type": "order_name_length",
                    "row": source_row["row_number"],
                    "message": "Il nome rapido può contenere al massimo 120 caratteri.",
                }
            )
            continue
        normalized_proposed = normalize_text(proposed)
        prod_key = str(getattr(product, "id", None) or getattr(product, "sku_interno", None) or normalize_text(product.canonical_name))
        existing_owner = existing_name_owners.get(normalized_proposed)
        proposed_owner = proposed_name_owners.get(normalized_proposed)

        is_same_product = (existing_owner == prod_key) or (getattr(product, "id", None) is not None and existing_owner == str(product.id))
        if existing_owner is not None and not is_same_product:
            errors.append(
                {
                    "type": "duplicate_order_name",
                    "row": source_row["row_number"],
                    "message": f"Il nome rapido '{proposed}' è già assegnato a un altro prodotto.",
                }
            )
            continue
        if proposed_owner is not None and proposed_owner != prod_key:
            errors.append(
                {
                    "type": "duplicate_order_name",
                    "row": source_row["row_number"],
                    "message": f"Il nome rapido '{proposed}' compare su più prodotti diversi nel foglio.",
                }
            )
            continue
        proposed_name_owners[normalized_proposed] = prod_key
        previous = order_name_changes_by_product.get(prod_key)
        if previous and previous["normalized_order_name"] != normalized_proposed:
            errors.append(
                {
                    "type": "conflicting_order_name",
                    "row": source_row["row_number"],
                    "message": "Lo stesso prodotto ha due nomi rapidi diversi nel foglio.",
                }
            )
            continue
        if normalized_proposed != (product.normalized_order_name or ""):
            order_name_changes_by_product[prod_key] = {
                "product_id": getattr(product, "id", None),
                "sku_interno": product.sku_interno,
                "canonical_name": product.canonical_name,
                "old_order_name": product.order_name,
                "new_order_name": proposed,
                "normalized_order_name": normalized_proposed,
            }

    product_ids = {product.id for _, product, _ in resolved_rows if getattr(product, "id", None) is not None}
    supplier_ids = {supplier.id for supplier in resolved_suppliers.values()}
    supplier_scope = await load_supplier_catalog_scope(db, supplier_ids=supplier_ids)
    aliases = []
    if product_ids and supplier_ids:
        aliases = (
            await db.scalars(
                select(SupplierProductAlias)
                .options(noload("*"))
                .where(
                    SupplierProductAlias.product_id.in_(product_ids),
                    SupplierProductAlias.supplier_id.in_(supplier_ids),
                    SupplierProductAlias.status == "approved",
                )
                .order_by(SupplierProductAlias.id)
            )
        ).all()
    aliases_by_pair: dict[tuple[int, int], list[SupplierProductAlias]] = defaultdict(list)
    for alias in aliases:
        aliases_by_pair[(alias.product_id, alias.supplier_id)].append(alias)

    skus = {
        product.sku_interno
        for _, product, _ in resolved_rows
        if product.sku_interno
    }
    active_prices = []
    if skus and supplier_ids:
        active_prices = (
            await db.scalars(
                select(ListinoMaster)
                .options(noload("*"))
                .where(
                    ListinoMaster.sku_interno.in_(skus),
                    ListinoMaster.fornitore_id.in_(supplier_ids),
                    ListinoMaster.data_scadenza.is_(None),
                )
                .order_by(ListinoMaster.id.desc())
            )
        ).all()
    prices_by_pair: dict[tuple[str, int], list[ListinoMaster]] = defaultdict(list)
    for price in active_prices:
        prices_by_pair[(price.sku_interno, price.fornitore_id)].append(price)

    changes: list[dict] = []
    seen_pairs: dict[tuple, int] = {}
    for source_row, product, mapping_method in resolved_rows:
        for index, header in enumerate(parsed["supplier_headers"]):
            raw_price = source_row["values"][index]
            if not raw_price.strip():
                continue
            supplier = resolved_suppliers.get(header)
            if not supplier:
                continue

            try:
                price = parse_decimal_price(raw_price)
            except ValueError as error:
                errors.append(
                    {
                        "type": "invalid_price",
                        "row": source_row["row_number"],
                        "column": header,
                        "message": str(error),
                    }
                )
                continue
            if price is None:
                continue

            # Verifica se il settore è esplicitamente escluso per questo fornitore
            norm_cat = (product.category or "").strip().casefold()
            is_explicitly_disabled = bool(
                norm_cat
                and getattr(supplier, "id", None)
                and supplier_scope.explicit_categories.get((supplier.id, norm_cat)) is False
            )
            if is_explicitly_disabled:
                errors.append(
                    {
                        "type": "supplier_scope",
                        "row": source_row["row_number"],
                        "product_id": getattr(product, "id", None),
                        "supplier_id": getattr(supplier, "id", None),
                        "column": header,
                        "message": (
                            f"{supplier.nome_azienda} è escluso esplicitamente per il settore "
                            f"“{product.category or product.canonical_name}”."
                        ),
                        "category": product.category,
                    }
                )
                continue

            prod_key = getattr(product, "id", None) or getattr(product, "sku_interno", None) or product.canonical_name
            supp_key = getattr(supplier, "id", None) or getattr(supplier, "partita_iva", None) or supplier.nome_azienda
            pair = (prod_key, supp_key)

            pair_aliases = aliases_by_pair.get((getattr(product, "id", None), getattr(supplier, "id", None)), [])
            normalized_ref = normalize_text(source_row["product_ref"])
            matching_alias = next(
                (
                    alias
                    for alias in pair_aliases
                    if alias.normalized_description == normalized_ref
                    or normalize_text(alias.raw_description) == normalized_ref
                    or normalize_text(alias.supplier_code or "") == normalized_ref
                ),
                None,
            )
            remember_alias = mapping_method == "explicit" and matching_alias is None
            current_rows = prices_by_pair.get((product.sku_interno, getattr(supplier, "id", None)), []) if product.sku_interno and getattr(supplier, "id", None) else []
            if len(current_rows) > 1:
                errors.append(
                    {
                        "type": "multiple_active_prices",
                        "row": source_row["row_number"],
                        "product_id": getattr(product, "id", None),
                        "supplier_id": getattr(supplier, "id", None),
                        "message": "Esistono più prezzi attivi: revisione manuale obbligatoria.",
                    }
                )
                continue
            current = current_rows[0] if current_rows else None
            # Risoluzione Unità di Misura per il singolo prodotto
            row_uom = (
                source_row.get("uom", "").strip()
                or product.comparison_unit
                or default_uom
                or "Pz"
            )

            same = bool(
                current
                and Decimal(str(current.prezzo_pattuito)) == price
                and current.unita_misura == row_uom
            )

            change_entry = {
                "row": source_row["row_number"],
                "product_id": getattr(product, "id", None),
                "sku_interno": product.sku_interno,
                "product_name": product.canonical_name,
                "supplier_id": getattr(supplier, "id", None),
                "supplier_name": supplier.nome_azienda,
                "supplier_product_alias_id": matching_alias.id if matching_alias else None,
                "source_product_ref": source_row["product_ref"],
                "remember_alias": remember_alias,
                "old_listino_id": current.id if current else None,
                "old_price": _price_string(Decimal(str(current.prezzo_pattuito))) if current else None,
                "new_price": _price_string(price),
                "uom": row_uom,
                "category": category or product.category or "Beverage",
                "action": "unchanged" if same else ("update" if current else "create"),
            }

            if pair in seen_pairs:
                # Se la stessa combinazione compare più volte nel foglio, aggiorna l'entry esistente con l'ultimo prezzo
                existing_idx = seen_pairs[pair]
                changes[existing_idx] = change_entry
            else:
                seen_pairs[pair] = len(changes)
                changes.append(change_entry)

    counts = {"create": 0, "update": 0, "unchanged": 0, "errors": len(errors)}
    for change in changes:
        counts[change["action"]] += 1
    preview_payload = {
        "version": 2,
        "delimiter": parsed["delimiter"],
        "effective_date": effective_date.isoformat(),
        "default_uom": default_uom,
        "location_id": location_id,
        "supplier_mapping": mapping_report,
        "product_mapping": product_report,
        "order_name_changes": list(order_name_changes_by_product.values()),
        "changes": changes,
        "errors": errors,
        "counts": counts,
        "can_commit": not errors and bool(changes or order_name_changes_by_product),
    }
    canonical = json.dumps(preview_payload, sort_keys=True, separators=(",", ":"))
    now = datetime.now(timezone.utc)
    preview = SmartPriceSheetPreview(
        payload_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        preview_payload=preview_payload,
        commit_result=None,
        status="ready",
        location_id=location_id,
        created_by=actor_id,
        created_at=now,
        expires_at=now + timedelta(minutes=30),
    )
    db.add(preview)
    await db.flush()
    return preview


async def commit_price_preview(
    db: AsyncSession, preview_id, actor_id: int
) -> tuple[SmartPriceSheetPreview, dict]:
    preview = await db.scalar(
        select(SmartPriceSheetPreview)
        .where(SmartPriceSheetPreview.id == preview_id)
        .with_for_update()
    )
    if not preview or preview.created_by != actor_id:
        raise HTTPException(404, "Anteprima non trovata")
    if preview.status == "committed":
        return preview, preview.commit_result or {}
    now = datetime.now(timezone.utc)
    if preview.expires_at <= now:
        preview.status = "expired"
        raise HTTPException(410, "Anteprima scaduta: generarne una nuova")
    payload = preview.preview_payload
    if payload.get("errors") or not payload.get("can_commit"):
        raise HTTPException(409, "Anteprima non confermabile: correggere gli errori")

    effective_date = date.fromisoformat(payload["effective_date"])
    result = {
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "products_created": 0,
        "order_names_updated": 0,
        "aliases_created": 0,
        "listino_ids": [],
    }
    for name_change in payload.get("order_name_changes", []):
        prod_id = name_change.get("product_id")
        if not prod_id:
            continue
        product = await db.scalar(
            select(Product)
            .where(Product.id == prod_id)
            .with_for_update()
        )
        if not product:
            continue
        product.order_name = name_change["new_order_name"]
        product.normalized_order_name = name_change["normalized_order_name"]
        result["order_names_updated"] += 1

    for change in payload["changes"]:
        product_id = change.get("product_id")
        product = None
        if product_id:
            product = await db.get(Product, product_id)
        if not product:
            norm_name = normalize_text(change["product_name"])
            product = await db.scalar(
                select(Product).where(
                    or_(
                        Product.sku_interno == change["sku_interno"],
                        Product.canonical_name == change["product_name"],
                        Product.normalized_name == norm_name,
                    )
                )
            )
            if not product:
                ord_name = next(
                    (nc["new_order_name"] for nc in payload.get("order_name_changes", []) if (nc.get("sku_interno") and nc.get("sku_interno") == change.get("sku_interno")) or nc.get("canonical_name") == change.get("product_name")),
                    None
                )
                product = Product(
                    sku_interno=change["sku_interno"] or f"IMP-{hashlib.sha256(norm_name.encode('utf-8')).hexdigest()[:10].upper()}",
                    canonical_name=change["product_name"].strip(),
                    normalized_name=norm_name,
                    order_name=ord_name,
                    normalized_order_name=normalize_text(ord_name) if ord_name else None,
                    category=change.get("category") or infer_category(change["product_name"]) or "Beverage",
                    comparison_unit=change.get("uom") or "Pz",
                    is_active=True,
                )
                db.add(product)
                await db.flush()
                result["products_created"] += 1
            elif change.get("category") and product.category != change["category"]:
                product.category = change["category"]
            change["product_id"] = product.id

        # Risoluzione o creazione del fornitore (se provvisorio)
        supplier_id = change.get("supplier_id")
        supplier = None
        if supplier_id:
            supplier = await db.get(Fornitore, supplier_id)
        if not supplier:
            norm_supp_name = normalize_text(change["supplier_name"])
            supplier = await db.scalar(
                select(Fornitore).where(
                    or_(
                        Fornitore.nome_azienda == change["supplier_name"].strip(),
                        func.lower(Fornitore.nome_azienda) == norm_supp_name.lower(),
                    )
                )
            )
            if not supplier:
                temp_piva = f"TEMP{hashlib.sha256(norm_supp_name.encode('utf-8')).hexdigest()[:7].upper()}"
                supplier = Fornitore(
                    nome_azienda=change["supplier_name"].strip(),
                    partita_iva=temp_piva,
                    attivo_whitelist=True,
                )
                db.add(supplier)
                await db.flush()
                result["suppliers_created"] = result.get("suppliers_created", 0) + 1
            change["supplier_id"] = supplier.id

        alias_id = change.get("supplier_product_alias_id")
        if change.get("remember_alias") and not alias_id:
            normalized_ref = normalize_text(change["source_product_ref"])
            existing_alias = await db.scalar(
                select(SupplierProductAlias)
                .options(noload("*"))
                .where(
                    SupplierProductAlias.supplier_id == change["supplier_id"],
                    SupplierProductAlias.normalized_description == normalized_ref,
                    SupplierProductAlias.status == "approved",
                )
                .with_for_update()
            )
            if existing_alias and existing_alias.product_id != change["product_id"]:
                raise HTTPException(
                    409,
                    "La descrizione del fornitore è stata associata a un altro prodotto: "
                    "rigenerare l'anteprima.",
                )
            if existing_alias:
                alias_id = existing_alias.id
            else:
                alias = SupplierProductAlias(
                    supplier_id=change["supplier_id"],
                    product_id=change["product_id"],
                    supplier_code=None,
                    raw_description=change["source_product_ref"].strip(),
                    normalized_description=normalized_ref,
                    ean=None,
                    pack_qty=None,
                    volume_ml=None,
                    weight_g=None,
                    container_type=None,
                    status="approved",
                    confidence_score=Decimal("1.00"),
                    source="smart_price_sheet",
                    first_seen_at=now,
                    last_seen_at=now,
                    created_at=now,
                    updated_at=now,
                )
                db.add(alias)
                await db.flush()
                alias_id = alias.id
                result["aliases_created"] += 1
        if change["action"] == "unchanged":
            result["unchanged"] += 1
            continue
        current = None
        if change["old_listino_id"] is not None:
            current = await db.scalar(
                select(ListinoMaster)
                .options(noload("*"))
                .where(ListinoMaster.id == change["old_listino_id"])
                .with_for_update()
            )
            if (
                not current
                or current.data_scadenza is not None
                or _price_string(Decimal(str(current.prezzo_pattuito))) != change["old_price"]
            ):
                raise HTTPException(409, "Il listino è cambiato: rigenerare l'anteprima")
        else:
            concurrent = await db.scalar(
                select(ListinoMaster)
                .options(noload("*"))
                .where(
                    ListinoMaster.fornitore_id == change["supplier_id"],
                    ListinoMaster.sku_interno == change["sku_interno"],
                    ListinoMaster.data_scadenza.is_(None),
                )
                .with_for_update()
            )
            if concurrent:
                raise HTTPException(409, "È comparso un prezzo attivo: rigenerare l'anteprima")

        if current:
            current.data_scadenza = (
                effective_date - timedelta(days=1)
                if effective_date > current.data_inizio_validita
                else effective_date
            )
            result["updated"] += 1
        else:
            result["created"] += 1
        new_price = ListinoMaster(
            fornitore_id=change["supplier_id"],
            sku_interno=change["sku_interno"],
            descrizione=change["product_name"],
            prezzo_pattuito=Decimal(change["new_price"]),
            unita_misura=change["uom"],
            data_inizio_validita=effective_date,
            data_scadenza=None,
            supplier_product_alias_id=alias_id,
        )
        db.add(new_price)
        await db.flush()
        result["listino_ids"].append(new_price.id)

    preview.status = "committed"
    preview.committed_at = now
    preview.commit_result = result
    await db.flush()
    return preview, result
