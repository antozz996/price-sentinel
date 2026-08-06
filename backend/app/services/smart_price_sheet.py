"""Safe clipboard preview and idempotent append-only price commit helpers."""

import csv
import hashlib
import io
import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.models.fornitori import Fornitore
from app.models.listino import ListinoMaster
from app.models.products import Product, SupplierProductAlias
from app.models.purchase_policy import SmartPriceSheetPreview
from app.services.normalization import normalize_text


MAX_ROWS = 5000
MAX_SUPPLIERS = 100


def parse_decimal_price(raw: object) -> Decimal | None:
    value = str(raw or "").strip().replace("€", "").replace(" ", "")
    if not value or value.lower() in {"-", "n/a", "nd", "n.d."}:
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
    except InvalidOperation as error:
        raise ValueError(f"Prezzo non valido: {raw}") from error
    if parsed <= 0 or parsed >= Decimal("100000000"):
        raise ValueError(f"Prezzo fuori intervallo: {raw}")
    if parsed.as_tuple().exponent < -4:
        raise ValueError(f"Sono ammessi al massimo 4 decimali: {raw}")
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
    if len(rows) < 2 or len(rows[0]) < 2:
        raise ValueError("Servono una riga intestazioni e almeno una riga prodotto")
    if len(rows) - 1 > MAX_ROWS:
        raise ValueError(f"Massimo {MAX_ROWS} prodotti per operazione")
    if len(rows[0]) - 1 > MAX_SUPPLIERS:
        raise ValueError(f"Massimo {MAX_SUPPLIERS} fornitori per operazione")
    width = len(rows[0])
    normalized_rows = [row + [""] * (width - len(row)) for row in rows[1:]]
    if any(len(row) > width for row in normalized_rows):
        raise ValueError("Una o più righe hanno più colonne dell'intestazione")
    supplier_headers = rows[0][1:]
    if any(not header for header in supplier_headers):
        raise ValueError("Le intestazioni fornitore non possono essere vuote")
    if len({normalize_text(item) for item in supplier_headers}) != len(supplier_headers):
        raise ValueError("Le intestazioni fornitore devono essere univoche")
    return {
        "delimiter": "tab" if delimiter == "\t" else delimiter,
        "product_header": rows[0][0] or "Prodotto",
        "supplier_headers": supplier_headers,
        "rows": [
            {"row_number": index + 2, "product_ref": row[0], "values": row[1:width]}
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
        if explicit_id is not None:
            supplier = supplier_by_id.get(explicit_id)
            method = "explicit"
        else:
            matches = supplier_by_name.get(normalize_text(header), [])
            supplier = matches[0] if len(matches) == 1 else None
            method = "exact_name" if supplier else "unresolved"
        if not supplier:
            errors.append(
                {
                    "type": "supplier_mapping",
                    "header": header,
                    "message": "Fornitore non trovato o ambiguo: selezionalo esplicitamente.",
                }
            )
        else:
            resolved_suppliers[header] = supplier
        mapping_report.append(
            {
                "header": header,
                "supplier_id": supplier.id if supplier else None,
                "supplier_name": supplier.nome_azienda if supplier else None,
                "method": method,
            }
        )

    products = (
        await db.scalars(select(Product).where(Product.is_active.is_(True)).order_by(Product.id))
    ).all()
    product_by_id = {row.id: row for row in products}
    product_candidates: dict[str, list[Product]] = defaultdict(list)
    for row in products:
        for value in {row.sku_interno, row.canonical_name, row.normalized_name}:
            if value:
                product_candidates[normalize_text(value)].append(row)

    resolved_rows: list[tuple[dict, Product]] = []
    product_report: list[dict] = []
    for source_row in parsed["rows"]:
        ref = source_row["product_ref"]
        explicit_id = product_mapping.get(ref)
        if explicit_id is not None:
            product = product_by_id.get(explicit_id)
            method = "explicit"
        else:
            unique = {item.id: item for item in product_candidates.get(normalize_text(ref), [])}
            product = next(iter(unique.values())) if len(unique) == 1 else None
            method = "exact_catalog" if product else "unresolved"
        if not product:
            errors.append(
                {
                    "type": "product_mapping",
                    "row": source_row["row_number"],
                    "reference": ref,
                    "message": "Prodotto non trovato o ambiguo: selezionalo dal catalogo canonico.",
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
            resolved_rows.append((source_row, product))
        product_report.append(
            {
                "row": source_row["row_number"],
                "reference": ref,
                "product_id": product.id if product else None,
                "sku_interno": product.sku_interno if product else None,
                "canonical_name": product.canonical_name if product else None,
                "method": method,
            }
        )

    product_ids = {product.id for _, product in resolved_rows}
    supplier_ids = {supplier.id for supplier in resolved_suppliers.values()}
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

    skus = {product.sku_interno for _, product in resolved_rows if product.sku_interno}
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
    seen_pairs: set[tuple[int, int]] = set()
    for source_row, product in resolved_rows:
        for index, header in enumerate(parsed["supplier_headers"]):
            raw_price = source_row["values"][index]
            if not raw_price.strip():
                continue
            supplier = resolved_suppliers.get(header)
            if not supplier:
                continue
            pair = (product.id, supplier.id)
            if pair in seen_pairs:
                errors.append(
                    {
                        "type": "duplicate_cell",
                        "row": source_row["row_number"],
                        "product_id": product.id,
                        "supplier_id": supplier.id,
                        "message": "La stessa coppia prodotto/fornitore compare più volte.",
                    }
                )
                continue
            seen_pairs.add(pair)
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
            pair_aliases = aliases_by_pair.get(pair, [])
            if len(pair_aliases) > 1:
                errors.append(
                    {
                        "type": "ambiguous_alias",
                        "row": source_row["row_number"],
                        "product_id": product.id,
                        "supplier_id": supplier.id,
                        "message": "Più alias approvati: correggere l'identità prima del prezzo.",
                    }
                )
                continue
            current_rows = prices_by_pair.get((product.sku_interno, supplier.id), [])
            if len(current_rows) > 1:
                errors.append(
                    {
                        "type": "multiple_active_prices",
                        "row": source_row["row_number"],
                        "product_id": product.id,
                        "supplier_id": supplier.id,
                        "message": "Esistono più prezzi attivi: revisione manuale obbligatoria.",
                    }
                )
                continue
            current = current_rows[0] if current_rows else None
            same = bool(
                current
                and Decimal(str(current.prezzo_pattuito)) == price
                and current.unita_misura == default_uom
            )
            changes.append(
                {
                    "row": source_row["row_number"],
                    "product_id": product.id,
                    "sku_interno": product.sku_interno,
                    "product_name": product.canonical_name,
                    "supplier_id": supplier.id,
                    "supplier_name": supplier.nome_azienda,
                    "supplier_product_alias_id": pair_aliases[0].id if pair_aliases else None,
                    "old_listino_id": current.id if current else None,
                    "old_price": _price_string(Decimal(str(current.prezzo_pattuito))) if current else None,
                    "new_price": _price_string(price),
                    "uom": default_uom,
                    "action": "unchanged" if same else ("update" if current else "create"),
                }
            )

    counts = {"create": 0, "update": 0, "unchanged": 0, "errors": len(errors)}
    for change in changes:
        counts[change["action"]] += 1
    preview_payload = {
        "version": 1,
        "delimiter": parsed["delimiter"],
        "effective_date": effective_date.isoformat(),
        "default_uom": default_uom,
        "location_id": location_id,
        "supplier_mapping": mapping_report,
        "product_mapping": product_report,
        "changes": changes,
        "errors": errors,
        "counts": counts,
        "can_commit": not errors and any(item["action"] != "unchanged" for item in changes),
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
    result = {"created": 0, "updated": 0, "unchanged": 0, "listino_ids": []}
    for change in payload["changes"]:
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
            supplier_product_alias_id=change["supplier_product_alias_id"],
        )
        db.add(new_price)
        await db.flush()
        result["listino_ids"].append(new_price.id)

    preview.status = "committed"
    preview.committed_at = now
    preview.commit_result = result
    await db.flush()
    return preview, result
