"""Acquisti per voce nel Listino Smart: quante fatture, quanta spesa, ultima data.

Regole dalla base comune (services/purchase_lines.py):

- acquisti = fatture distinte che contengono la voce con almeno una riga che
  conta come acquisto pagato (counts_for_average: niente note di credito
  TD04/TD08, niente omaggi);
- spesa = somma del netto riga con segno (pu x (1 - sconto/100) x quantita',
  note di credito in negativo);
- ultimo_acquisto = data documento piu' recente tra le stesse fatture d'acquisto;
- tenant, skus_esclusi e righe_escluse_statistiche come in purchase_lines_select.

Una sola query aggregata per tutte le voci (raggruppata per sku_interno), usata
sia per ordinare il catalogo prima della paginazione sia per i valori di pagina.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import distinct, func, select

from app.models.products import Product
from app.services.purchase_lines import (
    counts_for_average,
    line_net_amount,
    purchase_lines_select,
)

SORT_OPTIONS = ("nome", "acquisti", "spesa")
PERIOD_OPTIONS = ("tutto", "12m")


def period_start(periodo: str, today: date) -> Optional[date]:
    """Primo giorno incluso del periodo; None = tutto lo storico."""
    if periodo == "12m":
        return today - timedelta(days=365)
    return None


def purchase_stats_select(
    user,
    *,
    skus: Optional[Iterable[str]] = None,
    location_id: Optional[int] = None,
    date_from: Optional[date] = None,
):
    """SELECT sku_interno, acquisti, spesa, ultimo_acquisto raggruppato per voce."""
    lines = purchase_lines_select(
        user,
        skus=skus,
        location_ids=[location_id] if location_id is not None else None,
        date_from=date_from,
        require_sku=True,
    ).subquery("righe_acquisto")
    c = lines.c
    return select(
        c.sku_interno.label("sku_interno"),
        func.count(distinct(c.fattura_id)).filter(c.in_media).label("acquisti"),
        func.coalesce(func.sum(c.importo_netto), 0).label("spesa"),
        func.max(c.data_documento).filter(c.in_media).label("ultimo_acquisto"),
    ).group_by(c.sku_interno)


def matrix_order_by(sort: str, stats=None) -> list:
    """Ordine della matrice: nome (come prima) oppure acquisti/spesa decrescenti."""
    by_name = [Product.canonical_name, Product.id]
    if sort not in ("acquisti", "spesa") or stats is None:
        return by_name
    acquisti = func.coalesce(stats.c.acquisti, 0)
    spesa = func.coalesce(stats.c.spesa, 0)
    if sort == "acquisti":
        return [acquisti.desc(), spesa.desc(), *by_name]
    return [spesa.desc(), acquisti.desc(), *by_name]


def matrix_page_select(product_filter: list, sort: str, stats=None):
    """Pagina di voci: con sort acquisti/spesa unisce le statistiche e ordina PRIMA di limit/offset."""
    if sort in ("acquisti", "spesa") and stats is not None:
        return (
            select(Product, stats.c.acquisti, stats.c.spesa, stats.c.ultimo_acquisto)
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


def stats_payload(acquisti: Any, spesa: Any, ultimo_acquisto: Any) -> dict:
    """Campi della riga di matrice (spesa come stringa decimale, data ISO)."""
    value = Decimal(str(spesa)) if spesa is not None else Decimal("0")
    return {
        "acquisti": int(acquisti or 0),
        "spesa": f"{value:.2f}",
        "ultimo_acquisto": ultimo_acquisto.isoformat() if ultimo_acquisto else None,
    }


def purchase_stats_from_lines(lines: Iterable[Any]) -> dict[str, PurchaseStats]:
    """Stesse regole in Python, su righe gia' filtrate per tenant/esclusioni/sede.

    Ogni riga espone sku_interno, fattura_id, data_documento, tipo_documento,
    prezzo_unitario, sconto_percentuale, quantita, is_omaggio.
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
    for sku, ids in invoices.items():
        out[sku].acquisti = len(ids)
    return out


def sort_key(sort: str, name: str, stats: Optional[PurchaseStats]):
    """Chiave Python equivalente a matrix_order_by (per test e controlli sui CSV)."""
    stats = stats or PurchaseStats()
    if sort == "acquisti":
        return (-stats.acquisti, -stats.spesa, name)
    if sort == "spesa":
        return (-stats.spesa, -stats.acquisti, name)
    return (name,)
