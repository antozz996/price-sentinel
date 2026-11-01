"""Signed, variant-specific import of prices already approved in the normalized Sheet."""

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.models.fornitori import Fornitore
from app.models.listino import ListinoMaster
from app.models.products import Product, SupplierProductAlias
from app.models.purchase_policy import SmartPriceSheetPreview
from app.schemas.smart_price_sheet import VariantPricePreviewRequest
from app.services.normalization import normalize_text
from app.services.supplier_catalog_scope import load_supplier_catalog_scope


def _identity(sku: str, supplier_id: int) -> str:
    """Stable identity for a legacy single-offer row without column M."""
    digest = hashlib.sha256(f"{sku}\0{supplier_id}".encode()).hexdigest()[:20].upper()
    return f"SG-{digest}"


def _dimensions(quantity: Decimal | None, unit: str | None) -> tuple[int | None, int | None, int | None]:
    if quantity is None or not unit:
        return None, None, None
    normalized = normalize_text(unit)
    if normalized in {"kg", "chilo", "chili"}:
        amount = quantity * 1000
        return (1, None, int(amount)) if amount == int(amount) else (None, None, None)
    if normalized in {"g", "gr", "grammo", "grammi"}:
        return (1, None, int(quantity)) if quantity == int(quantity) else (None, None, None)
    if normalized in {"l", "lt", "litro", "litri"}:
        amount = quantity * 1000
        return (1, int(amount), None) if amount == int(amount) else (None, None, None)
    if normalized in {"cl"}:
        amount = quantity * 10
        return (1, int(amount), None) if amount == int(amount) else (None, None, None)
    if normalized in {"ml"}:
        return (1, int(quantity), None) if quantity == int(quantity) else (None, None, None)
    if normalized in {"pz", "pezzi", "pezzo", "bt", "bottiglie", "bottiglia"}:
        return (int(quantity), None, None) if quantity == int(quantity) else (None, None, None)
    return None, None, None


def _price_state(row: ListinoMaster | None) -> dict | None:
    if row is None:
        return None
    return {"id": row.id, "price": f"{Decimal(str(row.prezzo_pattuito)):.4f}",
            "unit": row.unita_misura, "start": row.data_inizio_validita.isoformat()}


def _alias_state(alias: SupplierProductAlias | None) -> dict | None:
    if alias is None:
        return None
    return {"id": alias.id, "product_id": alias.product_id, "status": alias.status,
            "description": alias.raw_description, "brand": alias.brand,
            "pack_qty": alias.pack_qty, "volume_ml": alias.volume_ml, "weight_g": alias.weight_g}


async def build_variant_preview(db: AsyncSession, request: VariantPricePreviewRequest, actor_id: int) -> SmartPriceSheetPreview:
    rows = request.rows
    products = {p.id: p for p in (await db.scalars(
        select(Product).options(noload("*")).where(Product.id.in_({r.product_id for r in rows}))
    )).all()}
    suppliers = {s.id: s for s in (await db.scalars(
        select(Fornitore).options(noload("*")).where(Fornitore.id.in_({r.supplier_id for r in rows}))
    )).all()}
    scope = await load_supplier_catalog_scope(db, supplier_ids=set(suppliers))
    ids = {(r.supplier_id, r.offer_id or _identity(r.sku, r.supplier_id)) for r in rows}
    aliases = {(a.supplier_id, a.supplier_code): a for a in (await db.scalars(
        select(SupplierProductAlias).options(noload("*")).where(
            SupplierProductAlias.supplier_id.in_({r.supplier_id for r in rows}),
            SupplierProductAlias.supplier_code.in_({code for _, code in ids}),
        )
    )).all()}
    alias_ids = [a.id for a in aliases.values()]
    active = {p.supplier_product_alias_id: p for p in (await db.scalars(
        select(ListinoMaster).options(noload("*")).where(
            ListinoMaster.supplier_product_alias_id.in_(alias_ids),
            ListinoMaster.data_scadenza.is_(None),
        ).order_by(ListinoMaster.id)
    )).all()}
    changes = []
    errors = []
    seen = set()
    pair_counts: dict[tuple[int, str], int] = {}
    for r in rows:
        pair = (r.supplier_id, r.sku)
        pair_counts[pair] = pair_counts.get(pair, 0) + 1
    for index, r in enumerate(rows, 1):
        offer_id = r.offer_id or _identity(r.sku, r.supplier_id)
        key = (r.supplier_id, offer_id)
        product, supplier = products.get(r.product_id), suppliers.get(r.supplier_id)
        if key in seen:
            errors.append({"row": index, "message": "ID offerta duplicato nell’anteprima."})
            continue
        seen.add(key)
        if pair_counts[(r.supplier_id, r.sku)] > 1 and not r.offer_id:
            errors.append({"row": index, "message": "Più offerte dello stesso fornitore richiedono ID_OFFERTA distinti nello Sheet."})
            continue
        if not product or not product.is_active or product.sku_interno != r.sku or not supplier or not supplier.attivo_whitelist or supplier.archived_at:
            errors.append({"row": index, "message": "Prodotto o fornitore non valido o non attivo."})
            continue
        if r.supplier_id not in scope.eligible_supplier_ids(
            product_id=product.id, category=product.category, subcategory=product.subcategory,
            supplier_ids={supplier.id},
        ):
            errors.append({"row": index, "message": f"Fornitore {supplier.nome_azienda} non abilitato al prodotto/settore."})
            continue
        alias = aliases.get(key)
        if alias and alias.product_id != product.id:
            errors.append({"row": index, "message": "ID offerta già collegato a un altro prodotto."})
            continue
        if alias and alias.status != "approved":
            errors.append({"row": index, "message": "ID offerta sospeso o non approvato."})
            continue
        if alias and alias.source != "normalized_sheet_offer":
            errors.append({"row": index, "message": "ID offerta già usato da un’altra origine."})
            continue
        pack_qty, volume_ml, weight_g = _dimensions(r.quantity, r.unit)
        if r.quantity and r.unit and pack_qty is None:
            errors.append({"row": index, "message": "Quantità o unità non convertibile con certezza."})
            continue
        current = active.get(alias.id) if alias else None
        price = f"{r.price.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP):.4f}"
        unit = "conf" if r.package_confirmed and pack_qty is not None and product.comparison_unit else None
        same = bool(current and _price_state(current)["price"] == price
                    and current.unita_misura == unit)
        changes.append({
            "product_id": product.id, "supplier_id": supplier.id, "sku": r.sku,
            "offer_id": offer_id, "description": r.description.strip(),
            "brand": r.brand.strip() if r.brand else None,
            "pack_qty": pack_qty, "volume_ml": volume_ml, "weight_g": weight_g,
            "price": price, "price_unit": unit, "old": _price_state(current),
            "alias_id": alias.id if alias else None, "old_alias": _alias_state(alias),
            "action": "unchanged" if same else "update" if current else "create",
        })
    counts = {name: sum(c["action"] == name for c in changes) for name in ("create", "update", "unchanged")}
    counts["errors"] = len(errors)
    payload = {"version": 3, "effective_date": request.effective_date.isoformat(),
               "changes": changes, "errors": errors, "counts": counts,
               "can_commit": bool(changes) and not errors}
    now = datetime.now(timezone.utc)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    preview = SmartPriceSheetPreview(
        payload_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        preview_payload=payload, status="ready", created_by=actor_id,
        created_at=now, expires_at=now + timedelta(minutes=30),
    )
    db.add(preview)
    await db.flush()
    return preview


async def commit_variant_preview(db: AsyncSession, preview: SmartPriceSheetPreview) -> dict:
    payload = preview.preview_payload
    effective_date = date.fromisoformat(payload["effective_date"])
    now = datetime.now(timezone.utc)
    result = {"status": "committed", "created": 0, "updated": 0, "unchanged": 0,
              "aliases_created": 0, "listino_ids": []}
    scope = await load_supplier_catalog_scope(db, supplier_ids={c["supplier_id"] for c in payload["changes"]})
    for change in payload["changes"]:
        # Serialize commits for the same supplier/offer even across different preview tokens.
        advisory_key = int.from_bytes(hashlib.sha256(
            f"{change['supplier_id']}:{change['offer_id']}".encode()).digest()[:8], "big", signed=True)
        await db.execute(select(func.pg_advisory_xact_lock(advisory_key)))
        product = await db.get(Product, change["product_id"])
        supplier = await db.get(Fornitore, change["supplier_id"])
        if (not product or not product.is_active or product.sku_interno != change["sku"]
                or not supplier or not supplier.attivo_whitelist or supplier.archived_at):
            raise HTTPException(409, "Prodotto o fornitore modificato: rigenerare l’anteprima.")
        if supplier.id not in scope.eligible_supplier_ids(
            product_id=product.id, category=product.category, subcategory=product.subcategory,
            supplier_ids={supplier.id},
        ):
            raise HTTPException(409, "Abilitazione del fornitore cambiata: rigenerare l’anteprima.")
        alias = await db.scalar(select(SupplierProductAlias).options(noload("*")).where(
            SupplierProductAlias.supplier_id == change["supplier_id"],
            SupplierProductAlias.supplier_code == change["offer_id"],
        ).with_for_update())
        if _alias_state(alias) != change["old_alias"]:
            raise HTTPException(409, "L’associazione dell’offerta è cambiata: rigenerare l’anteprima.")
        current = await db.scalar(select(ListinoMaster).options(noload("*")).where(
            ListinoMaster.supplier_product_alias_id == alias.id if alias else ListinoMaster.id == -1,
            ListinoMaster.data_scadenza.is_(None),
        ).order_by(ListinoMaster.id.desc()).limit(1).with_for_update())
        if _price_state(current) != change["old"]:
            raise HTTPException(409, "Il prezzo dell’offerta è cambiato: rigenerare l’anteprima.")
        if current and change["action"] != "unchanged" and effective_date <= current.data_inizio_validita:
            raise HTTPException(409, "Nuovo prezzo con decorrenza non successiva al prezzo attivo.")
        if not alias:
            alias = SupplierProductAlias(
                supplier_id=supplier.id, product_id=product.id, supplier_code=change["offer_id"],
                raw_description=change["description"], brand=change["brand"],
                normalized_description=normalize_text(change["description"]),
                pack_qty=change["pack_qty"], volume_ml=change["volume_ml"], weight_g=change["weight_g"],
                status="approved", confidence_score=Decimal("1.00"), source="normalized_sheet_offer",
                first_seen_at=now, last_seen_at=now, created_at=now, updated_at=now,
            )
            db.add(alias)
            await db.flush()
            result["aliases_created"] += 1
        else:
            alias.raw_description = change["description"]
            alias.normalized_description = normalize_text(change["description"])
            alias.brand = change["brand"]
            alias.pack_qty, alias.volume_ml, alias.weight_g = change["pack_qty"], change["volume_ml"], change["weight_g"]
            alias.last_seen_at = now
            alias.updated_at = now
        if change["action"] == "unchanged":
            result["unchanged"] += 1
            continue
        if current:
            current.data_scadenza = effective_date - timedelta(days=1)
            result["updated"] += 1
        else:
            result["created"] += 1
        price = ListinoMaster(
            fornitore_id=supplier.id, sku_interno=product.sku_interno,
            descrizione=change["description"], prezzo_pattuito=Decimal(change["price"]),
            unita_misura=change["price_unit"], data_inizio_validita=effective_date,
            data_scadenza=None, supplier_product_alias_id=alias.id,
        )
        db.add(price)
        await db.flush()
        result["listino_ids"].append(price.id)
    preview.status = "committed"
    preview.committed_at = now
    preview.commit_result = result
    await db.flush()
    return result
