"""Deterministic reconciliation; fuzzy results are suggestions only.

Regole sui prezzi e sulle quantità (rapporto schermate 14/11/2026, A11-A13, M27, B11):
- prezzo di fattura = netto riga (pu x (1 - sconto)) per unità di fattura, dalla base
  comune purchase_lines; il confronto con il listino avviene nell'unità del listino
  (o della voce, se il listino non ha unità) con il fattore di line_conversion, come il
  controllo anomalie. Se la conversione non è affidabile il prezzo non si confronta;
- ricezione non registrata (received_quantity NULL) = "awaiting_receipt": nessun
  confronto di quantità, nessuna contestazione;
- le note di credito (TD04/TD08) non si associano a un ordine;
- righe di fattura uguali possono coprire la stessa riga d'ordine: il doppione si
  segnala solo sull'eccedenza rispetto al ricevuto (o all'ordinato).
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from difflib import SequenceMatcher

from sqlalchemy import case, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

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
from app.models.supplier_identity_equivalence import SupplierIdentityEquivalence
from app.services.purchase_lines import AliasIndex, document_sign, line_conversion, line_net_unit_price
from app.services.supplier_identity_equivalence import active_equivalence_for_pair

AWAITING_RECEIPT = "awaiting_receipt"
_PRICE_QUANT = Decimal("0.000001")
_AMOUNT_QUANT = Decimal("0.01")


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


def is_credit_note(invoice: Fattura) -> bool:
    """TD04/TD08: un reso non è la fattura di un ordine (le sue righe sono positive nel database)."""
    return document_sign(invoice.tipo_documento) < 0


@dataclass(frozen=True)
class ExpectedPrice:
    """Prezzo di riferimento della riga: listino valido alla data o prezzo approvato del mese."""

    price: Decimal
    source: str
    unit: str | None  # unità del listino; None = unità di confronto della voce


@dataclass(frozen=True)
class PriceCheck:
    """Confronto prezzo nell'unità del listino. reliable=False: prezzo non confrontabile."""

    status: str  # no_reference, unverifiable, ok
    expected: Decimal | None = None
    invoiced: Decimal | None = None  # prezzo di fattura nell'unità del listino
    delta: Decimal | None = None  # per unità del listino
    units: Decimal | None = None  # quantità fatturata nell'unità del listino
    factor: Decimal | None = None  # unità del listino in una unità di fattura
    comparison_unit: str | None = None
    explanation: str = ""

    @property
    def reliable(self) -> bool:
        return self.status == "ok"

    def evidence(self) -> dict:
        def text(value):
            return str(value) if value is not None else None

        return {
            "status": self.status,
            "comparison_unit": self.comparison_unit,
            "expected_price": text(self.expected),
            "invoiced_price": text(self.invoiced),
            "factor": text(self.factor),
            "invoiced_units": text(self.units),
            "explanation": self.explanation,
        }


def compare_line_price(line, product: Product | None, alias: SupplierProductAlias | None, expected: ExpectedPrice | None) -> PriceCheck:
    """Porta il prezzo netto della riga nell'unità del listino con la base comune.

    Il listino è già nella sua unità; la riga si converte con line_conversion
    (strict_pack: senza confezione nota non si indovina). Senza conversione
    affidabile il prezzo resta visibile ma non si confronta.
    """
    if expected is None:
        return PriceCheck("no_reference", explanation="Nessun listino o prezzo approvato alla data della fattura")
    conversion = line_conversion(
        product=product,
        alias=alias,
        unita_misura=line.unita_misura_fattura,
        descrizione=line.descrizione_fornitore_raw,
        target_unit=expected.unit or None,
    )
    if not conversion.reliable or not conversion.factor:
        return PriceCheck(
            "unverifiable", expected=expected.price, comparison_unit=conversion.comparison_unit,
            explanation=f"Prezzo non confrontabile con il listino: {conversion.explanation}",
        )
    net = line_net_unit_price(line.prezzo_unitario_fatturato, line.sconto_percentuale)
    invoiced = conversion.unit_price(net).quantize(_PRICE_QUANT, rounding=ROUND_HALF_UP)
    return PriceCheck(
        "ok",
        expected=expected.price,
        invoiced=invoiced,
        delta=invoiced - expected.price,
        units=conversion.quantity(line.quantita),
        factor=conversion.factor,
        comparison_unit=conversion.comparison_unit,
        explanation=conversion.explanation,
    )


def price_overcharge(check: PriceCheck, tolerance_absolute, tolerance_percent) -> Decimal | None:
    """Importo contestato (delta x quantità nell'unità del listino) se oltre le tolleranze, altrimenti None."""
    if not check.reliable or check.delta is None:
        return None
    percent = (check.delta / check.expected * 100) if check.expected else Decimal("0")
    if check.delta > Decimal(tolerance_absolute) and percent > Decimal(tolerance_percent):
        return (check.delta * check.units).quantize(_AMOUNT_QUANT, rounding=ROUND_HALF_UP)
    return None


def _received(value) -> Decimal | None:
    """None quando la ricezione non è registrata: non è una ricezione di zero colli."""
    return Decimal(value) if value is not None else None


def quantity_outcome(
    *,
    invoiced: Decimal,
    received: Decimal | None,
    ordered: Decimal,
    consumed_before: Decimal,
    is_last: bool,
    signature_seen: bool,
) -> tuple[Decimal | None, bool]:
    """Quantità di una riga di fattura che condivide la riga d'ordine con le precedenti.

    Ritorna (quantity_delta, doppione). Le righe della stessa voce si confrontano
    sul totale: ogni riga porta solo l'eccedenza che aggiunge oltre il ricevuto; il
    "fatturato in meno" si legge sull'ultima riga del gruppo. Una riga uguale a una
    precedente (stessa quantità e prezzo) è un doppione solo se cade tutta oltre il
    ricevuto (o l'ordinato, se la ricezione non è registrata). Ricezione non
    registrata: nessun confronto di quantità (None).
    """
    capacity = received if received is not None else ordered
    duplicate = signature_seen and invoiced > 0 and consumed_before >= capacity
    if received is None:
        return None, duplicate
    after = consumed_before + invoiced
    zero = Decimal("0")
    over = max(zero, after - received) - max(zero, consumed_before - received)
    if over > 0:
        return over, duplicate
    if is_last and after < received:
        return after - received, duplicate
    return zero, duplicate


def line_outcome(
    *,
    compatible: bool,
    duplicate: bool,
    quantity_delta: Decimal | None,
    net_price: Decimal,
    check: PriceCheck,
    tolerance_absolute,
    tolerance_percent,
) -> tuple[str, str | None, Decimal | None]:
    """(match_status, anomaly_type, disputed_amount) di una riga abbinata a una riga d'ordine."""
    if duplicate:
        return "ambiguous", "duplicate_invoice_line", None
    if not compatible:
        return "unit_mismatch", "unit_mismatch", None
    if quantity_delta is not None and quantity_delta > 0:
        return "quantity_mismatch", "quantity_overbilled", (quantity_delta * net_price).quantize(_AMOUNT_QUANT, rounding=ROUND_HALF_UP)
    if quantity_delta is not None and quantity_delta < 0:
        return "quantity_mismatch", "quantity_underbilled", None
    disputed = price_overcharge(check, tolerance_absolute, tolerance_percent)
    if disputed is not None:
        return "price_mismatch", "price_overcharge", disputed
    return "matched", None, None


def _line_outcome(*, reconciliation: PurchaseOrderReconciliation, **kwargs):
    return line_outcome(
        tolerance_absolute=reconciliation.price_tolerance_absolute,
        tolerance_percent=reconciliation.price_tolerance_percent,
        **kwargs,
    )


def _with_checks(evidence: dict | None, check: PriceCheck, received: Decimal | None) -> dict:
    """Evidenza della riga con l'esito del confronto prezzo e lo stato della ricezione."""
    return {
        **(evidence or {}),
        "price_check": check.evidence(),
        "receipt_status": AWAITING_RECEIPT if received is None else "received",
    }


def _reason_with_receipt(reason: str | None, received: Decimal | None) -> str | None:
    if received is not None:
        return reason
    note = "In attesa di ricezione: quantità non confrontata"
    return f"{reason} · {note}" if reason else note


def matching_confidence(confidences: list[Decimal]) -> Decimal:
    """Media della sicurezza degli abbinamenti delle righe di fattura (0 senza righe)."""
    return sum(confidences, Decimal("0")) / len(confidences) if confidences else Decimal("0")


async def _alias_index(db: AsyncSession, supplier_id: int) -> AliasIndex:
    return AliasIndex((await db.scalars(
        select(SupplierProductAlias).options(noload("*")).where(SupplierProductAlias.supplier_id == supplier_id)
    )).all())


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
    if is_credit_note(invoice):
        # A credit note is a refund, not the invoice of an order: its positive
        # lines would read as goods billed twice or goods never ordered.
        raise ReconciliationError("credit_note_not_attachable", 409)
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
    equivalence = None
    if order.supplier_id != invoice.fornitore_id:
        equivalence = await active_equivalence_for_pair(
            db, order.supplier_id, invoice.fornitore_id
        )
        if not equivalence:
            raise ReconciliationError("cross_supplier_invoice_forbidden", 409)
    existing = await db.scalar(select(PurchaseOrderReconciliation).where(
        PurchaseOrderReconciliation.fattura_id == invoice.id,
        PurchaseOrderReconciliation.id != reconciliation.id,
    ).with_for_update())
    if existing and not allow_reassociate:
        raise ReconciliationError("invoice_already_associated", 409)
    if existing:
        existing.fattura_id = None
        existing.invoice_supplier_id = None
        existing.supplier_equivalence_id = None
        existing.supplier_equivalence_approved_by = None
        existing.supplier_equivalence_approved_at = None
        existing.supplier_equivalence_used_at = None
        existing.supplier_equivalence_reason_snapshot = None
        existing.status = "awaiting_invoice"
        existing.reconciliation_version += 1
        existing.updated_at = datetime.now(timezone.utc)
        await db.execute(delete(PurchaseOrderReconciliationItem).where(
            PurchaseOrderReconciliationItem.reconciliation_id == existing.id
        ))
    reconciliation.fattura_id = invoice.id
    reconciliation.supplier_id = order.supplier_id
    reconciliation.invoice_supplier_id = invoice.fornitore_id
    if equivalence:
        reconciliation.supplier_equivalence_id = equivalence.id
        reconciliation.supplier_equivalence_approved_by = equivalence.approved_by
        reconciliation.supplier_equivalence_approved_at = equivalence.approved_at
        reconciliation.supplier_equivalence_used_at = datetime.now(timezone.utc)
        reconciliation.supplier_equivalence_reason_snapshot = equivalence.reason
    else:
        reconciliation.supplier_equivalence_id = None
        reconciliation.supplier_equivalence_approved_by = None
        reconciliation.supplier_equivalence_approved_at = None
        reconciliation.supplier_equivalence_used_at = None
        reconciliation.supplier_equivalence_reason_snapshot = None
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
    reconciliation.invoice_supplier_id = None
    reconciliation.supplier_equivalence_id = None
    reconciliation.supplier_equivalence_approved_by = None
    reconciliation.supplier_equivalence_approved_at = None
    reconciliation.supplier_equivalence_used_at = None
    reconciliation.supplier_equivalence_reason_snapshot = None
    reconciliation.status = "awaiting_invoice"
    reconciliation.matching_confidence = Decimal("0")
    reconciliation.reconciliation_version += 1
    reconciliation.started_at = None
    reconciliation.completed_at = None
    reconciliation.updated_at = datetime.now(timezone.utc)


async def _expected_price(db: AsyncSession, supplier_id: int, product: Product | None, invoice: Fattura) -> ExpectedPrice | None:
    if not product or not product.sku_interno:
        return None
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
        # Listino senza unità: vale l'unità di confronto della voce, come nel controllo anomalie.
        return ExpectedPrice(
            Decimal(price.prezzo_pattuito), f"listino_master:{price.id}", (price.unita_misura or "").strip() or None
        )
    approved = await db.scalar(select(ApprovazionePrezzo).where(
        ApprovazionePrezzo.sku_interno == product.sku_interno,
        ApprovazionePrezzo.mese == invoice.data_documento.strftime("%Y-%m"),
    ).limit(1))
    if approved:
        return ExpectedPrice(Decimal(approved.prezzo_approvato), f"ultimo_prezzo_approvato:{approved.mese}", None)
    return None


async def _explicit_product(
    db: AsyncSession,
    line: RigaFattura,
    supplier_ids: list[int],
) -> tuple[int | None, str | None, Decimal, str, int | None]:
    if line.sku_interno:
        product = await db.scalar(select(Product).where(Product.sku_interno == line.sku_interno).limit(1))
        if product:
            return product.id, "product_id", Decimal("1"), "SKU canonico esplicito sulla riga fattura", None
    code = (line.codice_fornitore_raw or "").strip()
    if code:
        alias = await db.scalar(select(SupplierProductAlias).where(
            SupplierProductAlias.supplier_id.in_(supplier_ids),
            SupplierProductAlias.status == "approved",
            or_(SupplierProductAlias.supplier_code == code, SupplierProductAlias.ean == code),
        ).order_by(
            case(
                {
                    supplier_id: position
                    for position, supplier_id in enumerate(supplier_ids)
                },
                value=SupplierProductAlias.supplier_id,
                else_=len(supplier_ids),
            ),
            SupplierProductAlias.id,
        ).limit(1))
        if alias:
            method = "ean" if alias.ean == code else "supplier_product_alias"
            return alias.product_id, method, Decimal("0.99"), f"Alias fornitore esplicito {alias.id}", alias.supplier_id
        legacy = await db.scalar(select(AliasProdotto).where(
            AliasProdotto.fornitore_id.in_(supplier_ids),
            AliasProdotto.codice_fornitore_originale == code,
        ).order_by(
            case(
                {
                    supplier_id: position
                    for position, supplier_id in enumerate(supplier_ids)
                },
                value=AliasProdotto.fornitore_id,
                else_=len(supplier_ids),
            ),
            AliasProdotto.id,
        ).limit(1))
        if legacy and legacy.sku_interno:
            product = await db.scalar(select(Product).where(Product.sku_interno == legacy.sku_interno).limit(1))
            if product:
                return product.id, "supplier_product_alias", Decimal("0.98"), f"Alias legacy esplicito {legacy.id}", legacy.fornitore_id
    return None, None, Decimal("0"), "Nessuna associazione esplicita", None


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
    if is_credit_note(invoice):
        raise ReconciliationError("credit_note_not_attachable", 409)
    alias_supplier_ids = [invoice.fornitore_id]
    if order.supplier_id != invoice.fornitore_id:
        equivalence = await db.get(
            SupplierIdentityEquivalence,
            reconciliation.supplier_equivalence_id,
        )
        if (
            not equivalence
            or not equivalence.is_active
            or {
                equivalence.canonical_supplier_id,
                equivalence.equivalent_supplier_id,
            }
            != {order.supplier_id, invoice.fornitore_id}
        ):
            raise ReconciliationError(
                "supplier_equivalence_inactive_or_invalid", 409
            )
        alias_supplier_ids.append(order.supplier_id)
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
    alias_index = await _alias_index(db, invoice.fornitore_id)
    matched_orders: set[int] = set()
    confidences: list[Decimal] = []
    anomaly_count = 0

    # Pass 1: explicit product of every line, so that repeated lines of the same
    # product can share one order line (quantities compared on their total).
    resolved = [
        (line, *await _explicit_product(db, line, alias_supplier_ids))
        for line in invoice_lines
    ]
    items_by_product: dict[int, list[LiquidStockSupplierOrderItem]] = {}
    for order_item in order_items:
        if order_item.product_id is not None:
            items_by_product.setdefault(order_item.product_id, []).append(order_item)
    last_line_of_item: dict[int, int] = {}
    for line, product_id, *_ in resolved:
        group = items_by_product.get(product_id) if product_id is not None else None
        if group and len(group) == 1 and units_compatible(group[0].unit, line.unita_misura_fattura):
            last_line_of_item[group[0].id] = line.id
    consumed: dict[int, Decimal] = {}
    seen_signatures: dict[int, set] = {}

    for line, product_id, method, confidence, reason, alias_supplier_id in resolved:
        group = items_by_product.get(product_id, []) if product_id is not None else []
        # A single order line of the product can cover several invoice lines;
        # two or more order lines of the same product need a manual choice.
        candidates = group if len(group) == 1 else [item for item in group if item.id not in matched_orders]
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
                    invoiced_unit_price=line_net_unit_price(line.prezzo_unitario_fatturato, line.sconto_percentuale), match_status="ambiguous", anomaly_type="ambiguous_match",
                    match_method="candidate_only", match_confidence=Decimal(str(evidence["fallback_candidates"][0]["score"])),
                    match_reason="Fallback descrittivo proposto; conferma manuale obbligatoria", candidate_evidence=evidence,
                    created_at=now, updated_at=now,
                )
                db.add(item); anomaly_count += 1; confidences.append(item.match_confidence); continue
            item = PurchaseOrderReconciliationItem(
                reconciliation_id=reconciliation.id, riga_fattura_id=line.id, product_id=product_id,
                invoiced_quantity=Decimal(line.quantita), invoiced_unit=line.unita_misura_fattura,
                invoice_product_description=line.descrizione_fornitore_raw,
                invoiced_unit_price=line_net_unit_price(line.prezzo_unitario_fatturato, line.sconto_percentuale), match_status="unordered_item", anomaly_type="unordered_item",
                match_method=method, match_confidence=confidence, match_reason=reason, candidate_evidence=evidence,
                match_alias_supplier_id=alias_supplier_id,
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
                invoiced_unit_price=line_net_unit_price(line.prezzo_unitario_fatturato, line.sconto_percentuale), match_status="ambiguous", anomaly_type="ambiguous_match",
                match_method=method, match_confidence=confidence, match_reason="Più righe ordine compatibili", candidate_evidence=evidence,
                match_alias_supplier_id=alias_supplier_id,
                created_at=now, updated_at=now,
            )
            db.add(item); anomaly_count += 1; confidences.append(confidence); continue
        matched_orders.add(chosen.id)
        ordered = Decimal(chosen.ordered_quantity)
        received = _received(chosen.received_quantity)
        invoiced = Decimal(line.quantita)
        net_price = line_net_unit_price(line.prezzo_unitario_fatturato, line.sconto_percentuale)
        product = products.get(product_id)
        alias = alias_index.resolve(invoice.fornitore_id, product_id, line.codice_fornitore_raw, line.descrizione_fornitore_raw)
        expected = await _expected_price(db, invoice.fornitore_id, product, invoice)
        check = compare_line_price(line, product, alias, expected)
        compatible = units_compatible(chosen.unit, line.unita_misura_fattura)
        quantity_delta = None
        duplicate = False
        if compatible:
            signature = (Decimal(line.quantita), net_price)
            quantity_delta, duplicate = quantity_outcome(
                invoiced=invoiced, received=received, ordered=ordered,
                consumed_before=consumed.get(chosen.id, Decimal("0")),
                is_last=last_line_of_item.get(chosen.id) == line.id,
                signature_seen=signature in seen_signatures.setdefault(chosen.id, set()),
            )
            consumed[chosen.id] = consumed.get(chosen.id, Decimal("0")) + invoiced
            seen_signatures[chosen.id].add(signature)
        status, anomaly, disputed = _line_outcome(
            compatible=compatible, duplicate=duplicate, quantity_delta=quantity_delta, net_price=net_price,
            check=check, reconciliation=reconciliation,
        )
        evidence = _with_checks(evidence, check, received)
        if anomaly: anomaly_count += 1
        item = PurchaseOrderReconciliationItem(
            reconciliation_id=reconciliation.id, liquidstock_item_id=chosen.liquidstock_supplier_order_item_id,
            riga_fattura_id=line.id, product_id=product_id, ordered_quantity=ordered, received_quantity=received,
            order_product_name=chosen.product_name_snapshot,
            invoice_product_description=line.descrizione_fornitore_raw,
            ordered_package_note=chosen.package_note,
            invoiced_quantity=invoiced, ordered_unit=chosen.unit, invoiced_unit=line.unita_misura_fattura,
            expected_unit_price=check.expected, expected_price_source=expected.source if expected else None,
            invoiced_unit_price=net_price,
            quantity_delta=quantity_delta, price_delta=check.delta, disputed_amount=disputed,
            match_status=status, anomaly_type=anomaly, match_method=method, match_confidence=confidence,
            match_reason=_reason_with_receipt(reason, received), match_alias_supplier_id=alias_supplier_id,
            candidate_evidence=evidence, created_at=now, updated_at=now,
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
            received_quantity=_received(order_item.received_quantity), ordered_unit=order_item.unit,
            match_status="missing_invoice_item", anomaly_type="missing_invoice_item", match_method="unmatched_order_line",
            match_confidence=Decimal("1"), match_reason="Riga ordine non presente in fattura", created_at=now, updated_at=now,
        )); anomaly_count += 1
    # Confidence of the invoice-line matches only: order lines missing from the
    # invoice are anomalies, not certain matches, and must not raise the average.
    reconciliation.matching_confidence = matching_confidence(confidences)
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
        evidence={
            "match_method": item.match_method,
            "reason": item.match_reason,
            "match_alias_supplier_id": item.match_alias_supplier_id,
            "order_supplier_id": reconciliation.supplier_id,
            "invoice_supplier_id": reconciliation.invoice_supplier_id,
            "supplier_equivalence_id": reconciliation.supplier_equivalence_id,
            "quantity_delta": str(item.quantity_delta) if item.quantity_delta is not None else None,
            "price_delta": str(item.price_delta) if item.price_delta is not None else None,
        },
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
    received = _received(target.received_quantity)
    invoiced = Decimal(line.quantita)
    net_price = line_net_unit_price(line.prezzo_unitario_fatturato, line.sconto_percentuale)
    expected = await _expected_price(db, invoice.fornitore_id, product, invoice)
    alias = (await _alias_index(db, invoice.fornitore_id)).resolve(
        invoice.fornitore_id, target.product_id, line.codice_fornitore_raw, line.descrizione_fornitore_raw
    )
    check = compare_line_price(line, product, alias, expected)
    compatible = units_compatible(target.unit, line.unita_misura_fattura)
    quantity_delta = None
    if compatible:
        quantity_delta, _ = quantity_outcome(
            invoiced=invoiced, received=received, ordered=ordered,
            consumed_before=Decimal("0"), is_last=True, signature_seen=False,
        )
    status, anomaly, disputed = _line_outcome(
        compatible=compatible, duplicate=False, quantity_delta=quantity_delta, net_price=net_price,
        check=check, reconciliation=reconciliation,
    )

    item.liquidstock_item_id = target.liquidstock_supplier_order_item_id
    item.product_id = target.product_id
    item.order_product_name = target.product_name_snapshot
    item.invoice_product_description = line.descrizione_fornitore_raw
    item.ordered_package_note = target.package_note
    item.ordered_quantity = ordered
    item.received_quantity = received
    item.ordered_unit = target.unit
    item.expected_unit_price = check.expected
    item.expected_price_source = expected.source if expected else None
    item.invoiced_unit_price = net_price
    item.quantity_delta = quantity_delta
    item.price_delta = check.delta
    item.disputed_amount = disputed
    item.match_status = status
    item.anomaly_type = anomaly
    item.match_method = "manual_confirmation"
    item.match_confidence = Decimal("1")
    item.match_reason = _reason_with_receipt("Confermato manualmente dall’operatore", received)
    item.match_alias_supplier_id = None
    item.candidate_evidence = _with_checks(item.candidate_evidence, check, received)
    item.notes = notes
