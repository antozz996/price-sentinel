"""Acquisti per voce nel Listino Smart: quante fatture, quanta spesa, ultima data.

Regole dalla base comune (services/purchase_lines.py):

- acquisti = fatture distinte che contengono la voce con almeno una riga che
  conta come acquisto pagato (counts_for_average: niente note di credito
  TD04/TD08, niente omaggi);
- spesa = somma del netto riga con segno (pu x (1 - sconto/100) x quantita',
  note di credito in negativo);
- ultimo_acquisto = data documento piu' recente tra le stesse fatture d'acquisto;
- quantita = somma delle quantita' convertite nell'unita' di confronto della voce
  (conversion_table/converted_quantity_sql), note di credito in negativo, omaggi
  esclusi; le righe con conversione non affidabile non si sommano e finiscono in
  quantita_non_convertita per unita' di fattura normalizzata (es. {"KG": "30"});
- tenant, skus_esclusi e righe_escluse_statistiche come in purchase_lines_select.

Una sola query aggregata per tutte le voci (raggruppata per sku_interno), usata
sia per ordinare il catalogo prima della paginazione sia per i valori di pagina;
prima si caricano le conversioni (load_conversions, combinazioni distinte).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional

from sqlalchemy import String, cast, distinct, func, select
from sqlalchemy.dialects.postgresql import JSONB

from app.models.products import Product
from app.services.normalization import unit_family
from app.services.purchase_lines import (
    ConversionKey,
    LineConversion,
    conversion_join,
    conversion_key,
    conversion_table,
    converted_quantity_sql,
    counts_for_average,
    is_free_line,
    line_net_amount,
    load_conversions,
    normalized_unit,
    purchase_lines_select,
    signed_quantity,
)

SORT_OPTIONS = ("nome", "acquisti", "spesa", "quantita")
STAT_SORTS = ("acquisti", "spesa", "quantita")
STAT_COLUMNS = ("acquisti", "spesa", "ultimo_acquisto", "quantita", "quantita_non_convertita")
PERIOD_OPTIONS = ("tutto", "12m")


def period_start(periodo: str, today: date) -> Optional[date]:
    """Primo giorno incluso del periodo; None = tutto lo storico."""
    if periodo == "12m":
        return today - timedelta(days=365)
    return None


def purchase_lines_subquery(
    user,
    *,
    skus: Optional[Iterable[str]] = None,
    location_id: Optional[int] = None,
    date_from: Optional[date] = None,
):
    """Righe d'acquisto collegate a una voce (base comune), come subquery."""
    return purchase_lines_select(
        user,
        skus=skus,
        location_ids=[location_id] if location_id is not None else None,
        date_from=date_from,
        require_sku=True,
    ).subquery("righe_acquisto")


def purchase_stats_select(
    user,
    *,
    skus: Optional[Iterable[str]] = None,
    location_id: Optional[int] = None,
    date_from: Optional[date] = None,
    conversions: Optional[Mapping[ConversionKey, LineConversion]] = None,
    lines=None,
):
    """SELECT per voce: sku_interno, acquisti, spesa, ultimo_acquisto, quantita, quantita_non_convertita.

    conversions: risultato di load_conversions() sulla stessa subquery `lines`
    (senza conversioni nessuna riga e' affidabile e tutto resta non convertito).
    """
    if lines is None:
        lines = purchase_lines_subquery(user, skus=skus, location_id=location_id, date_from=date_from)
    conv = conversion_table(conversions or {}, "conv_acquisti")
    c = lines.c
    joined = lines.outerjoin(conv, conversion_join(lines, conv))
    paid_or_credit = c.is_omaggio.is_(False)  # omaggi esclusi dalla quantita'
    unreliable = conv.c.reliable.is_not(True)
    base = (
        select(
            c.sku_interno.label("sku_interno"),
            func.count(distinct(c.fattura_id)).filter(c.in_media).label("acquisti"),
            func.coalesce(func.sum(c.importo_netto), 0).label("spesa"),
            func.max(c.data_documento).filter(c.in_media).label("ultimo_acquisto"),
            func.coalesce(
                func.sum(converted_quantity_sql(lines, conv)).filter(paid_or_credit), 0
            ).label("quantita"),
        )
        .select_from(joined)
        .group_by(c.sku_interno)
        .subquery("acquisti_base")
    )
    per_unit = (
        select(
            c.sku_interno.label("sku_interno"),
            c.unita.label("unita"),
            func.sum(c.quantita_firmata).label("quantita"),
        )
        .select_from(joined)
        .where(paid_or_credit, unreliable)
        .group_by(c.sku_interno, c.unita)
        .having(func.sum(c.quantita_firmata) != 0)
        .subquery("non_convertite_unita")
    )
    not_converted = (
        select(
            per_unit.c.sku_interno.label("sku_interno"),
            func.jsonb_object_agg(per_unit.c.unita, cast(per_unit.c.quantita, String), type_=JSONB)
            .label("quantita_non_convertita"),
        )
        .group_by(per_unit.c.sku_interno)
        .subquery("non_convertite")
    )
    return select(
        base.c.sku_interno,
        base.c.acquisti,
        base.c.spesa,
        base.c.ultimo_acquisto,
        base.c.quantita,
        not_converted.c.quantita_non_convertita,
    ).outerjoin(not_converted, not_converted.c.sku_interno == base.c.sku_interno)


async def load_purchase_stats_select(
    db,
    user,
    *,
    skus: Optional[Iterable[str]] = None,
    location_id: Optional[int] = None,
    date_from: Optional[date] = None,
):
    """Carica le conversioni (combinazioni distinte) e restituisce purchase_stats_select."""
    lines = purchase_lines_subquery(user, skus=skus, location_id=location_id, date_from=date_from)
    conversions = await load_conversions(db, lines)
    return purchase_stats_select(user, conversions=conversions, lines=lines)


def matrix_order_by(sort: str, stats=None) -> list:
    """Ordine della matrice: nome (come prima) oppure acquisti/spesa/quantita decrescenti."""
    by_name = [Product.canonical_name, Product.id]
    if sort not in STAT_SORTS or stats is None:
        return by_name
    acquisti = func.coalesce(stats.c.acquisti, 0)
    spesa = func.coalesce(stats.c.spesa, 0)
    if sort == "acquisti":
        return [acquisti.desc(), spesa.desc(), *by_name]
    if sort == "quantita":
        return [func.coalesce(stats.c.quantita, 0).desc(), acquisti.desc(), *by_name]
    return [spesa.desc(), acquisti.desc(), *by_name]


def matrix_page_select(product_filter: list, sort: str, stats=None):
    """Pagina di voci: con sort acquisti/spesa/quantita unisce le statistiche e ordina PRIMA di limit/offset."""
    if sort in STAT_SORTS and stats is not None:
        return (
            select(Product, *(stats.c[name] for name in STAT_COLUMNS))
            .outerjoin(stats, stats.c.sku_interno == Product.sku_interno)
            .where(*product_filter)
            .order_by(*matrix_order_by(sort, stats))
        )
    return select(Product).where(*product_filter).order_by(*matrix_order_by("nome"))


@dataclass
class PurchaseStats:
    acquisti: int = 0
    spesa: Decimal = Decimal("0")
    ultimo_acquisto: Optional[date] = None
    quantita: Decimal = Decimal("0")
    quantita_non_convertita: dict[str, Decimal] = field(default_factory=dict)


def quantity_text(value: Any) -> str:
    """Quantita' come stringa decimale senza zeri inutili (3 decimali al massimo): 312, 35.5, -2."""
    number = Decimal(str(value)) if value is not None else Decimal("0")
    number = number.quantize(Decimal("0.001"))
    if number == 0:
        return "0"
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def stats_payload(
    acquisti: Any,
    spesa: Any,
    ultimo_acquisto: Any,
    quantita: Any = None,
    quantita_non_convertita: Optional[Mapping[str, Any]] = None,
    comparison_unit: Optional[str] = None,
) -> dict:
    """Campi della riga di matrice (spesa e quantita' come stringhe decimali, data ISO)."""
    value = Decimal(str(spesa)) if spesa is not None else Decimal("0")
    not_converted = {
        unit: quantity_text(qty)
        for unit, qty in sorted((quantita_non_convertita or {}).items())
        if Decimal(str(qty or 0)).quantize(Decimal("0.001")) != 0
    }
    return {
        "acquisti": int(acquisti or 0),
        "spesa": f"{value:.2f}",
        "ultimo_acquisto": ultimo_acquisto.isoformat() if ultimo_acquisto else None,
        "quantita": quantity_text(quantita),
        "quantita_unita": unit_family(comparison_unit) or (comparison_unit or None),
        "quantita_non_convertita": not_converted,
    }


def purchase_stats_from_lines(
    lines: Iterable[Any],
    conversions: Optional[Mapping[ConversionKey, LineConversion]] = None,
) -> dict[str, PurchaseStats]:
    """Stesse regole in Python, su righe gia' filtrate per tenant/esclusioni/sede.

    Ogni riga espone sku_interno, fattura_id, data_documento, tipo_documento,
    prezzo_unitario, sconto_percentuale, quantita, is_omaggio. Con conversions
    (chiave conversion_key) servono anche fornitore_id, product_id,
    codice_fornitore, descrizione, unita_misura e si calcola la quantita'.
    """
    out: dict[str, PurchaseStats] = {}
    invoices: dict[str, set] = {}
    for line in lines:
        sku = line.sku_interno
        if not sku:
            continue
        stats = out.setdefault(sku, PurchaseStats())
        stats.spesa += line_net_amount(line.prezzo_unitario, line.sconto_percentuale, line.quantita, line.tipo_documento)
        if counts_for_average(line.is_omaggio, line.prezzo_unitario, line.sconto_percentuale, line.tipo_documento):
            invoices.setdefault(sku, set()).add(line.fattura_id)
            if stats.ultimo_acquisto is None or line.data_documento > stats.ultimo_acquisto:
                stats.ultimo_acquisto = line.data_documento
        if conversions is not None and not is_free_line(line.is_omaggio, line.prezzo_unitario, line.sconto_percentuale):
            qty = signed_quantity(line.quantita, line.tipo_documento)
            conv = conversions.get(conversion_key(line))
            converted = conv.quantity(qty) if conv is not None else None
            if converted is not None:
                stats.quantita += converted
            else:
                unit = normalized_unit(line.unita_misura)
                stats.quantita_non_convertita[unit] = stats.quantita_non_convertita.get(unit, Decimal("0")) + qty
    for sku, ids in invoices.items():
        out[sku].acquisti = len(ids)
    for stats in out.values():
        stats.quantita_non_convertita = {u: q for u, q in stats.quantita_non_convertita.items() if q != 0}
    return out


def sort_key(sort: str, name: str, stats: Optional[PurchaseStats]):
    """Chiave Python equivalente a matrix_order_by (per test e controlli sui CSV)."""
    stats = stats or PurchaseStats()
    if sort == "acquisti":
        return (-stats.acquisti, -stats.spesa, name)
    if sort == "spesa":
        return (-stats.spesa, -stats.acquisti, name)
    if sort == "quantita":
        return (-stats.quantita, -stats.acquisti, name)
    return (name,)
