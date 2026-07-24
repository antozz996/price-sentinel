"""Deterministic reconciliation; fuzzy results are suggestions only."""

import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from difflib import SequenceMatcher

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alias import AliasProdotto
from app.models.anomalie import ApprovazionePrezzo
from app.models.fatture import Fattura, RigaFattura
from app.models.liquidstock_integration import LiquidStockSupplierOrder, LiquidStockSupplierOrderItem
from app.models.listino import ListinoMaster
from app.models.products import Product, SupplierProductAlias
from app.models.purchase_order_reconciliation import (
    LiquidStockVenueMapping,
    PurchaseOrderReconciliation,
    PurchaseOrderReconciliationAnomaly,
    PurchaseOrderReconciliationItem,
)


class ReconciliationError(Exception):
    def __init__(self, code: str, status: int = 422):
        super().__init__(code)
        self.code = code
        self.status = status


def normalize(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def units_compatible(ordered: str | None, invoiced: str | None) -> bool:
    aliases = {"pz": "pezzo", "pzi": "pezzo", "pezzi": "pezzo", "nr": "pezzo", "kg": "kg", "kilogrammo": "kg", "lt": "litro", "l": "litro", "litri": "litro"}
    left = aliases.get(normalize(ordered), normalize(ordered))
    right = aliases.get(normalize(invoiced), normalize(invoiced))
    return bool(left and right and left == right)


async def ensure_reconciliation(db: AsyncSession, order: LiquidStockSupplierOrder) -> PurchaseOrderReconciliation:
    reconciliation = await db.scalar(
        select(PurchaseOrderReconciliation).where(
            PurchaseOrderReconciliation.liquidstock_supplier_order_id == order.liquidstock_supplier_order_id
        )
    )
    if reconciliation:
        return reconciliation
    now = datetime.now(timezone.utc)
    reconciliation = PurchaseOrderReconciliation(
        liquidstock_supplier_order_id=order.liquidstock_supplier_order_id,
        liquidstock_order_id=order.liquidstock_order_id,
        supplier_id=order.supplier_id,
        venue_id=order.liquidstock_venue_id,
        status="awaiting_invoice",
        matching_confidence=Decimal("0"),
        reconciliation_version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(reconciliation)
    await db.flush()
    return reconciliation


async def attach_invoice(
    db: AsyncSession,
    reconciliation: PurchaseOrderReconciliation,
    invoice: Fattura,
    *,
    allow_reassociate: bool,
    tolerance_absolute: Decimal,
    tolerance_percent: Decimal,
) -> PurchaseOrderReconciliation:
    order = await db.scalar(select(LiquidStockSupplierOrder).where(
        LiquidStockSupplierOrder.liquidstock_supplier_order_id == reconciliation.liquidstock_supplier_order_id
    ))
    if not order:
        raise ReconciliationError("order_not_found", 404)
    mapping = await db.scalar(select(LiquidStockVenueMapping).where(
        LiquidStockVenueMapping.liquidstock_venue_id == order.liquidstock_venue_id
    ))
    if not mapping or mapping.location_id != invoice.location_id:
        raise ReconciliationError("cross_venue_invoice_forbidden", 409)
    if order.supplier_id is None:
        raise ReconciliationError("supplier_mapping_required", 409)
    if order.supplier_id != invoice.fornitore_id:
        raise ReconciliationError("cross_supplier_invoice_forbidden", 409)
    existing = await db.scalar(select(PurchaseOrderReconciliation).where(
        PurchaseOrderReconciliation.fattura_id == invoice.id,
        PurchaseOrderReconciliation.id != reconciliation.id,
    ).with_for_update())
    if existing and not allow_reassociate:
        raise ReconciliationError("invoice_already_associated", 409)
    if existing:
        existing.fattura_id = None
        existing.status = "awaiting_invoice"
        existing.reconciliation_version += 1
        existing.updated_at = datetime.now(timezone.utc)
        await db.execute(delete(PurchaseOrderReconciliationItem).where(
            PurchaseOrderReconciliationItem.reconciliation_id == existing.id
        ))
    reconciliation.fattura_id = invoice.id
    reconciliation.supplier_id = invoice.fornitore_id
    reconciliation.status = "pending"
    reconciliation.price_tolerance_absolute = tolerance_absolute
    reconciliation.price_tolerance_percent = tolerance_percent
    reconciliation.reconciliation_version += 1
    reconciliation.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return reconciliation


async def detach_invoice(db: AsyncSession, reconciliation: PurchaseOrderReconciliation) -> None:
    if reconciliation.status == "closed":
        raise ReconciliationError("closed_reconciliation_is_immutable", 409)
    await db.execute(delete(PurchaseOrderReconciliationItem).where(
        PurchaseOrderReconciliationItem.reconciliation_id == reconciliation.id
    ))
    reconciliation.fattura_id = None
    reconciliation.status = "awaiting_invoice"
    reconciliation.matching_confidence = Decimal("0")
    reconciliation.reconciliation_version += 1
    reconciliation.started_at = None
    reconciliation.completed_at = None
    reconciliation.updated_at = datetime.now(timezone.utc)


async def _expected_price(db: AsyncSession, supplier_id: int, product: Product | None, invoice: Fattura) -> tuple[Decimal | None, str | None]:
    if not product or not product.sku_interno:
        return None, None
    price = await db.scalar(
        select(ListinoMaster)
        .where(
            ListinoMaster.fornitore_id == supplier_id,
            ListinoMaster.sku_interno == product.sku_interno,
            ListinoMaster.data_inizio_validita <= invoice.data_documento,
            or_(ListinoMaster.data_scadenza.is_(None), ListinoMaster.data_scadenza >= invoice.data_documento),
        )
        .order_by(ListinoMaster.data_inizio_validita.desc(), ListinoMaster.id.desc())
        .limit(1)
    )
    if price:
        return Decimal(price.prezzo_pattuito), f"listino_master:{price.id}"
    approved = await db.scalar(select(ApprovazionePrezzo).where(
        ApprovazionePrezzo.sku_interno == product.sku_interno,
        ApprovazionePrezzo.mese == invoice.data_documento.strftime("%Y-%m"),
    ).limit(1))
    if approved:
        return Decimal(approved.prezzo_approvato), f"ultimo_prezzo_approvato:{approved.mese}"
    return None, None


async def _explicit_product(db: AsyncSession, line: RigaFattura, supplier_id: int) -> tuple[int | None, str | None, Decimal, str]:
    if line.sku_interno:
        product = await db.scalar(select(Product).where(Product.sku_interno == line.sku_interno).limit(1))
        if product:
            return product.id, "product_id", Decimal("1"), "SKU canonico esplicito sulla riga fattura"
    code = (line.codice_fornitore_raw or "").strip()
    if code:
        alias = await db.scalar(select(SupplierProductAlias).where(
            SupplierProductAlias.supplier_id == supplier_id,
            SupplierProductAlias.status == "approved",
            or_(SupplierProductAlias.supplier_code == code, SupplierProductAlias.ean == code),
        ).order_by(SupplierProductAlias.id).limit(1))
        if alias:
            method = "ean" if alias.ean == code else "supplier_product_alias"
            return alias.product_id, method, Decimal("0.99"), f"Alias fornitore esplicito {alias.id}"
        legacy = await db.scalar(select(AliasProdotto).where(
            AliasProdotto.fornitore_id == supplier_id,
            AliasProdotto.codice_fornitore_originale == code,
        ).limit(1))
        if legacy and legacy.sku_interno:
            product = await db.scalar(select(Product).where(Product.sku_interno == legacy.sku_interno).limit(1))
            if product:
                return product.id, "supplier_product_alias", Decimal("0.98"), f"Alias legacy esplicito {legacy.id}"
    return None, None, Decimal("0"), "Nessuna associazione esplicita"


async def run_matching(db: AsyncSession, reconciliation: PurchaseOrderReconciliation) -> PurchaseOrderReconciliation:
    if reconciliation.status in {"reviewed", "closed"}:
        raise ReconciliationError("reviewed_reconciliation_is_immutable", 409)
    if not reconciliation.fattura_id:
        raise ReconciliationError("invoice_required", 409)
    order = await db.scalar(select(LiquidStockSupplierOrder).where(
        LiquidStockSupplierOrder.liquidstock_supplier_order_id == reconciliation.liquidstock_supplier_order_id
    ))
    invoice = await db.scalar(select(Fattura).where(Fattura.id == reconciliation.fattura_id))
    if not order or not invoice:
        raise ReconciliationError("reconciliation_reference_missing", 409)
    await db.execute(delete(PurchaseOrderReconciliationItem).where(
        PurchaseOrderReconciliationItem.reconciliation_id == reconciliation.id
    ))
    await db.flush()
    now = datetime.now(timezone.utc)
    reconciliation.status = "matching"
    reconciliation.started_at = now
    reconciliation.completed_at = None
    reconciliation.reconciliation_version += 1
    order_items = list((await db.scalars(select(LiquidStockSupplierOrderItem).where(
        LiquidStockSupplierOrderItem.supplier_order_id == order.id
    ).order_by(LiquidStockSupplierOrderItem.id))).all())
    invoice_lines = list((await db.scalars(select(RigaFattura).where(
        RigaFattura.fattura_id == invoice.id
    ).order_by(RigaFattura.numero_linea, RigaFattura.id))).all())
    products = {p.id: p for p in (await db.scalars(select(Product))).all()}
    matched_orders: set[int] = set()
    confidences: list[Decimal] = []
    anomaly_count = 0
    signatures = Counter((normalize(line.codice_fornitore_raw or line.descrizione_fornitore_raw), Decimal(line.quantita), Decimal(line.prezzo_netto_normalizzato)) for line in invoice_lines)

    for line in invoice_lines:
        product_id, method, confidence, reason = await _explicit_product(db, line, invoice.fornitore_id)
        candidates = [item for item in order_items if product_id is not None and item.product_id == product_id and item.id not in matched_orders]
        evidence: dict = {"explicit_product_id": product_id, "fallback_candidates": []}
        if not candidates:
            scored = sorted(((SequenceMatcher(None, normalize(line.descrizione_fornitore_raw), normalize(item.product_name_snapshot)).ratio(), item) for item in order_items if item.id not in matched_orders), key=lambda pair: pair[0], reverse=True)
            evidence["fallback_candidates"] = [
                {
                    "liquidstock_item_id": str(item.liquidstock_supplier_order_item_id),
                    "product_id": item.product_id,
                    "score": round(score, 4),
                    "method": "normalized_description",
                }
                for score, item in scored[:3]
                if score >= 0.55
            ]
            if product_id is None and evidence["fallback_candidates"]:
                item = PurchaseOrderReconciliationItem(
                    reconciliation_id=reconciliation.id, liquidstock_item_id=None, riga_fattura_id=line.id,
                    product_id=None, invoiced_quantity=Decimal(line.quantita), invoiced_unit=line.unita_misura_fattura,
                    invoice_product_description=line.descrizione_fornitore_raw,
                    invoiced_unit_price=Decimal(line.prezzo_netto_normalizzato), match_status="ambiguous", anomaly_type="ambiguous_match",
                    match_method="candidate_only", match_confidence=Decimal(str(evidence["fallback_candidates"][0]["score"])),
                    match_reason="Fallback descrittivo proposto; conferma manuale obbligatoria", candidate_evidence=evidence,
                    created_at=now, updated_at=now,
                )
                db.add(item); anomaly_count += 1; confidences.append(item.match_confidence); continue
            item = PurchaseOrderReconciliationItem(
                reconciliation_id=reconciliation.id, riga_fattura_id=line.id, product_id=product_id,
                invoiced_quantity=Decimal(line.quantita), invoiced_unit=line.unita_misura_fattura,
                invoice_product_description=line.descrizione_fornitore_raw,
                invoiced_unit_price=Decimal(line.prezzo_netto_normalizzato), match_status="unordered_item", anomaly_type="unordered_item",
                match_method=method, match_confidence=confidence, match_reason=reason, candidate_evidence=evidence,
                created_at=now, updated_at=now,
            )
            db.add(item); anomaly_count += 1; confidences.append(confidence); continue
        if len(candidates) > 1:
            chosen = None
        else:
            chosen = candidates[0]
        if chosen is None:
            item = PurchaseOrderReconciliationItem(
                reconciliation_id=reconciliation.id, riga_fattura_id=line.id, product_id=product_id,
                invoiced_quantity=Decimal(line.quantita), invoiced_unit=line.unita_misura_fattura,
                invoice_product_description=line.descrizione_fornitore_raw,
                invoiced_unit_price=Decimal(line.prezzo_netto_normalizzato), match_status="ambiguous", anomaly_type="ambiguous_match",
                match_method=method, match_confidence=confidence, match_reason="Più righe ordine compatibili", candidate_evidence=evidence,
                created_at=now, updated_at=now,
            )
            db.add(item); anomaly_count += 1; confidences.append(confidence); continue
        matched_orders.add(chosen.id)
        ordered = Decimal(chosen.ordered_quantity)
        received = Decimal(chosen.received_quantity or 0)
        invoiced = Decimal(line.quantita)
        expected, expected_source = await _expected_price(db, invoice.fornitore_id, products.get(product_id), invoice)
        invoiced_price = Decimal(line.prezzo_netto_normalizzato)
        compatible = units_compatible(chosen.unit, line.unita_misura_fattura)
        quantity_delta = invoiced - received if compatible else None
        price_delta = invoiced_price - expected if compatible and expected is not None else None
        disputed = None
        status = "matched"; anomaly = None
        signature = (normalize(line.codice_fornitore_raw or line.descrizione_fornitore_raw), Decimal(line.quantita), Decimal(line.prezzo_netto_normalizzato))
        if signatures[signature] > 1:
            status, anomaly = "ambiguous", "duplicate_invoice_line"
        elif not compatible:
            status, anomaly = "unit_mismatch", "unit_mismatch"
        elif quantity_delta and quantity_delta > 0:
            status, anomaly, disputed = "quantity_mismatch", "quantity_overbilled", quantity_delta * invoiced_price
        elif quantity_delta and quantity_delta < 0:
            status, anomaly = "quantity_mismatch", "quantity_underbilled"
        elif price_delta is not None:
            percent = (price_delta / expected * 100) if expected else Decimal("0")
            if price_delta > Decimal(reconciliation.price_tolerance_absolute) and percent > Decimal(reconciliation.price_tolerance_percent):
                status, anomaly, disputed = "price_mismatch", "price_overcharge", price_delta * invoiced
        if anomaly: anomaly_count += 1
        item = PurchaseOrderReconciliationItem(
            reconciliation_id=reconciliation.id, liquidstock_item_id=chosen.liquidstock_supplier_order_item_id,
            riga_fattura_id=line.id, product_id=product_id, ordered_quantity=ordered, received_quantity=received,
            order_product_name=chosen.product_name_snapshot,
            invoice_product_description=line.descrizione_fornitore_raw,
            ordered_package_note=chosen.package_note,
            invoiced_quantity=invoiced, ordered_unit=chosen.unit, invoiced_unit=line.unita_misura_fattura,
            expected_unit_price=expected, expected_price_source=expected_source, invoiced_unit_price=invoiced_price,
            quantity_delta=quantity_delta, price_delta=price_delta, disputed_amount=disputed,
            match_status=status, anomaly_type=anomaly, match_method=method, match_confidence=confidence,
            match_reason=reason, candidate_evidence=evidence, created_at=now, updated_at=now,
        )
        db.add(item); confidences.append(confidence)

    for order_item in order_items:
        if order_item.id in matched_orders:
            continue
        db.add(PurchaseOrderReconciliationItem(
            reconciliation_id=reconciliation.id, liquidstock_item_id=order_item.liquidstock_supplier_order_item_id,
            product_id=order_item.product_id, ordered_quantity=Decimal(order_item.ordered_quantity),
            order_product_name=order_item.product_name_snapshot,
            ordered_package_note=order_item.package_note,
            received_quantity=Decimal(order_item.received_quantity or 0), ordered_unit=order_item.unit,
            match_status="missing_invoice_item", anomaly_type="missing_invoice_item", match_method="unmatched_order_line",
            match_confidence=Decimal("1"), match_reason="Riga ordine non presente in fattura", created_at=now, updated_at=now,
        )); anomaly_count += 1; confidences.append(Decimal("1"))
    reconciliation.matching_confidence = sum(confidences, Decimal("0")) / len(confidences) if confidences else Decimal("0")
    reconciliation.status = "anomalies_found" if anomaly_count else "matched"
    reconciliation.completed_at = now
    reconciliation.updated_at = now
    await db.flush()
    return reconciliation


async def create_anomaly(db: AsyncSession, reconciliation: PurchaseOrderReconciliation, item: PurchaseOrderReconciliationItem, notes: str | None = None) -> PurchaseOrderReconciliationAnomaly:
    if not item.anomaly_type:
        raise ReconciliationError("item_has_no_anomaly", 409)
    key = f"item:{item.id}:{item.anomaly_type}"
    existing = await db.scalar(select(PurchaseOrderReconciliationAnomaly).where(
        PurchaseOrderReconciliationAnomaly.reconciliation_id == reconciliation.id,
        PurchaseOrderReconciliationAnomaly.evidence_key == key,
    ))
    if existing:
        return existing
    now = datetime.now(timezone.utc)
    anomaly = PurchaseOrderReconciliationAnomaly(
        reconciliation_id=reconciliation.id, reconciliation_item_id=item.id,
        fattura_id=reconciliation.fattura_id, riga_fattura_id=item.riga_fattura_id,
        liquidstock_supplier_order_id=reconciliation.liquidstock_supplier_order_id,
        liquidstock_item_id=item.liquidstock_item_id, supplier_id=reconciliation.supplier_id,
        venue_id=reconciliation.venue_id, anomaly_type=item.anomaly_type,
        disputed_amount=item.disputed_amount, evidence_key=key,
        evidence={"match_method": item.match_method, "reason": item.match_reason, "quantity_delta": str(item.quantity_delta) if item.quantity_delta is not None else None, "price_delta": str(item.price_delta) if item.price_delta is not None else None},
        workflow_status="da_verificare", notes=notes, created_at=now, updated_at=now,
    )
    db.add(anomaly); await db.flush(); return anomaly


async def confirm_candidate(
    db: AsyncSession,
    reconciliation: PurchaseOrderReconciliation,
    item: PurchaseOrderReconciliationItem,
    target: LiquidStockSupplierOrderItem,
    notes: str | None = None,
) -> None:
    """Confirm a suggested match without leaving a duplicate missing-item row."""
    conflict = await db.scalar(
        select(PurchaseOrderReconciliationItem).where(
            PurchaseOrderReconciliationItem.reconciliation_id == reconciliation.id,
            PurchaseOrderReconciliationItem.liquidstock_item_id
            == target.liquidstock_supplier_order_item_id,
            PurchaseOrderReconciliationItem.id != item.id,
        )
    )
    if conflict and conflict.match_status != "missing_invoice_item":
        raise ReconciliationError("confirmed_match_target_already_used", 409)
    if conflict:
        await db.delete(conflict)

    invoice = await db.get(Fattura, reconciliation.fattura_id)
    line = await db.get(RigaFattura, item.riga_fattura_id)
    product = await db.get(Product, target.product_id) if target.product_id else None
    if not invoice or not line:
        raise ReconciliationError("confirmed_match_reference_missing", 409)

    ordered = Decimal(target.ordered_quantity)
    received = Decimal(target.received_quantity or 0)
    invoiced = Decimal(line.quantita)
    invoiced_price = Decimal(line.prezzo_netto_normalizzato)
    expected, expected_source = await _expected_price(
        db, invoice.fornitore_id, product, invoice
    )
    compatible = units_compatible(target.unit, line.unita_misura_fattura)
    quantity_delta = invoiced - received if compatible else None
    price_delta = (
        invoiced_price - expected
        if compatible and expected is not None
        else None
    )
    status = "matched"
    anomaly = None
    disputed = None
    if not compatible:
        status, anomaly = "unit_mismatch", "unit_mismatch"
    elif quantity_delta and quantity_delta > 0:
        status, anomaly = "quantity_mismatch", "quantity_overbilled"
        disputed = quantity_delta * invoiced_price
    elif quantity_delta and quantity_delta < 0:
        status, anomaly = "quantity_mismatch", "quantity_underbilled"
    elif price_delta is not None:
        percent = (
            price_delta / expected * 100 if expected else Decimal("0")
        )
        if (
            price_delta > Decimal(reconciliation.price_tolerance_absolute)
            and percent > Decimal(reconciliation.price_tolerance_percent)
        ):
            status, anomaly = "price_mismatch", "price_overcharge"
            disputed = price_delta * invoiced

    item.liquidstock_item_id = target.liquidstock_supplier_order_item_id
    item.product_id = target.product_id
    item.order_product_name = target.product_name_snapshot
    item.invoice_product_description = line.descrizione_fornitore_raw
    item.ordered_package_note = target.package_note
    item.ordered_quantity = ordered
    item.received_quantity = received
    item.ordered_unit = target.unit
    item.expected_unit_price = expected
    item.expected_price_source = expected_source
    item.quantity_delta = quantity_delta
    item.price_delta = price_delta
    item.disputed_amount = disputed
    item.match_status = status
    item.anomaly_type = anomaly
    item.match_method = "manual_confirmation"
    item.match_confidence = Decimal("1")
    item.match_reason = "Confermato manualmente dall’operatore"
    item.notes = notes
