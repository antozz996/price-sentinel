"""Statistiche della pagina Recensioni prodotti.

- "Ordinato N volte": ordini distinti, non righe d'ordine (l'omaggio 5+1 è una
  seconda riga dello stesso ordine); righe per product_id e per sku della stessa
  voce si uniscono per ordine, non si sovrascrivono.
- "Fornitore abituale": il fornitore con più righe di fattura (non note di
  credito) negli ultimi 12 mesi, dalla base comune purchase_lines.
- "Miglior listino": solo listini validi oggi, di fornitori non archiviati, scelti
  sul prezzo nell'unità di confronto (cheapest_comparable_listino).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import noload

from app.models.fornitori import Fornitore
from app.models.listino import ListinoMaster
from app.models.products import SupplierProductAlias
from app.services.purchase_lines import purchase_lines_select
from app.services.purchase_recommendation import cheapest_comparable_listino

USUAL_SUPPLIER_DAYS = 365


class OrderIndex:
    """Ordini distinti per voce, da righe (ordine_id, product_id, sku_interno, data_ordine)."""

    def __init__(self, rows: Iterable[Any]):
        self._by_product: dict[int, dict[int, Any]] = {}
        self._by_sku: dict[str, dict[int, Any]] = {}
        for row in rows:
            if row.product_id:
                self._by_product.setdefault(row.product_id, {})[row.ordine_id] = row.data_ordine
            if row.sku_interno:
                self._by_sku.setdefault(row.sku_interno, {})[row.ordine_id] = row.data_ordine

    @property
    def product_ids(self) -> set[int]:
        return set(self._by_product)

    @property
    def skus(self) -> set[str]:
        return set(self._by_sku)

    def stats(self, product_id: Optional[int], sku: Optional[str]) -> tuple[int, Optional[datetime]]:
        """(numero di ordini distinti, data dell'ultimo ordine) della voce."""
        orders: dict[int, Any] = {}
        orders.update(self._by_product.get(product_id, {}) if product_id else {})
        orders.update(self._by_sku.get(sku, {}) if sku else {})
        dates = [d for d in orders.values() if d is not None]
        return len(orders), (max(dates) if dates else None)


def pick_usual_suppliers(rows: Iterable[Any]) -> dict[str, int]:
    """Per ogni sku il fornitore con più righe; a parità il più recente, poi l'id più basso.

    rows: (sku_interno, fornitore_id, righe, ultimo_acquisto).
    """
    best: dict[str, tuple] = {}
    for sku, fornitore_id, righe, ultimo in rows:
        key = (int(righe or 0), ultimo or date.min, -int(fornitore_id))
        if sku not in best or key > best[sku][0]:
            best[sku] = (key, fornitore_id)
    return {sku: value[1] for sku, value in best.items()}


async def usual_suppliers(db, user, skus: list[str], today: date) -> dict[str, int]:
    """Fornitore abituale per sku: righe di fattura TD01/TD24 degli ultimi 12 mesi."""
    if not skus:
        return {}
    lines = purchase_lines_select(
        user,
        date_from=today - timedelta(days=USUAL_SUPPLIER_DAYS),
        skus=skus,
        require_sku=True,
        include_excluded=True,  # un acquisto escluso dalle statistiche resta un acquisto
        include_credit_notes=False,
    ).subquery()
    rows = (await db.execute(
        select(lines.c.sku_interno, lines.c.fornitore_id, func.count(lines.c.riga_id), func.max(lines.c.data_documento))
        .group_by(lines.c.sku_interno, lines.c.fornitore_id)
    )).all()
    return pick_usual_suppliers(rows)


def pick_best_listino(rows: list, product, aliases_by_id: dict):
    """Listino più conveniente nell'unità di confronto.

    Se nessun listino è confrontabile (unità mancante o conversione incerta) ma
    sono tutti dello stesso fornitore, si mostra il suo listino più recente:
    non c'è nessun confronto da sbagliare. Altrimenti None.
    """
    best = cheapest_comparable_listino(rows, product, aliases_by_id)
    if best is not None:
        return best
    if rows and len({row.fornitore_id for row in rows}) == 1:
        return max(rows, key=lambda row: (row.data_inizio_validita, row.id))
    return None


async def best_current_listini(db, products: list, today: date) -> dict[str, ListinoMaster]:
    """Miglior listino valido oggi per sku (fornitori non archiviati)."""
    by_sku_product = {p.sku_interno: p for p in products if p.sku_interno}
    if not by_sku_product:
        return {}
    listini = (await db.scalars(
        select(ListinoMaster)
        .join(Fornitore, Fornitore.id == ListinoMaster.fornitore_id)
        .where(
            ListinoMaster.sku_interno.in_(list(by_sku_product)),
            ListinoMaster.data_inizio_validita <= today,
            or_(ListinoMaster.data_scadenza.is_(None), ListinoMaster.data_scadenza >= today),
            Fornitore.archived_at.is_(None),
        )
        .options(noload(ListinoMaster.pfa_scaglioni), noload(ListinoMaster.uom_conversioni))
    )).all()
    alias_ids = {row.supplier_product_alias_id for row in listini if row.supplier_product_alias_id}
    aliases_by_id = {
        alias.id: alias
        for alias in (await db.scalars(
            select(SupplierProductAlias).options(noload("*")).where(SupplierProductAlias.id.in_(alias_ids))
        )).all()
    } if alias_ids else {}
    rows_by_sku: dict[str, list] = {}
    for row in listini:
        rows_by_sku.setdefault(row.sku_interno, []).append(row)
    result: dict[str, ListinoMaster] = {}
    for sku, rows in rows_by_sku.items():
        best = pick_best_listino(rows, by_sku_product.get(sku), aliases_by_id)
        if best is not None:
            result[sku] = best
    return result
