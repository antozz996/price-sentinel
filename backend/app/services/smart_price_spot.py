"""Prezzo spot del Listino Smart: l'ultimo prezzo fatturato, convertito.

Regole (rapporto schermate 14/11/2026, A8, M17, B7):

- righe d'acquisto dalla base comune (services.purchase_lines): netto riga
  pu x (1 - sconto/100), niente note di credito TD04/TD08, niente omaggi,
  niente SKU o righe escluse dalle statistiche, filtro tenant e sede;
- il prezzo si converte nell'unità di confronto della voce con la stessa regola
  del controllo anomalie e dei listini (normalize_price_for_comparison non
  rigida, fattore confezione del collegamento), così spot e listino si
  confrontano nella stessa unità. L'alias si sceglie per codice, poi per
  descrizione (AliasIndex), poi l'unico collegamento approvato della coppia; se
  la coppia ha più collegamenti e nessuno corrisponde la conversione è incerta;
- per ogni sede vale l'ultima riga (data documento, poi id); tra le sedi si
  mostra il prezzo più basso tra questi ultimi prezzi. Nessuna finestra
  temporale: una riga più vecchia di SPOT_STALE_DAYS resta visibile ma è
  segnata come "vecchia";
- una riga con prezzo sotto il 20% della mediana della stessa coppia e della
  stessa unità di fattura (es. 0,01 su una riga a kg) non si usa;
- se la conversione non è affidabile la cella mostra il prezzo nella sua unità
  di fattura e resta fuori classifica (unit_price_normalized None).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import median
from typing import Any, Iterable, Mapping, Optional

from sqlalchemy import select

from app.models.fatture import Fattura, RigaFattura
from app.services.purchase_lines import (
    AliasIndex,
    LineConversion,
    counts_for_average_sql,
    line_conversion,
    line_net_unit_price,
    normalized_unit,
    purchase_lines_select,
)

SPOT_STALE_DAYS = 120
OUTLIER_RATIO = Decimal("0.2")


@dataclass(frozen=True)
class SpotLine:
    riga_id: int
    sku_interno: str
    fornitore_id: int
    location_id: Optional[int]
    data_documento: date
    codice_fornitore: Optional[str]
    descrizione: Optional[str]
    unita_misura: Optional[str]
    prezzo_unitario: Any
    sconto_percentuale: Any = 0

    @property
    def net(self) -> Decimal:
        return line_net_unit_price(self.prezzo_unitario, self.sconto_percentuale)


def spot_lines_query(user, *, skus, supplier_ids, location_id: Optional[int] = None):
    """Righe candidate allo spot, nell'ordine dei campi di SpotLine.

    Base comune: tenant, SKU/righe escluse, niente note di credito (TD04/TD08) e
    niente omaggi (counts_for_average_sql); sede se la vista è limitata a una sede.
    """
    lines = purchase_lines_select(
        user,
        skus=skus,
        fornitore_ids=supplier_ids,
        location_ids=[location_id] if location_id is not None else None,
        require_sku=True,
        include_credit_notes=False,
    ).where(counts_for_average_sql(RigaFattura, Fattura.tipo_documento)).subquery()
    c = lines.c
    return select(
        c.riga_id, c.sku_interno, c.fornitore_id, c.location_id, c.data_documento,
        c.codice_fornitore, c.descrizione, c.unita_misura, c.prezzo_unitario, c.sconto_percentuale,
    )


def _unique_pair_alias(aliases_by_pair, supplier_id, product_id):
    approved = [
        a for a in aliases_by_pair.get((supplier_id, product_id), [])
        if getattr(a, "status", "approved") == "approved"
    ]
    if len(approved) == 1:
        return approved[0], False
    return None, len(approved) > 1


def spot_conversion(line: SpotLine, product, alias_index: AliasIndex, aliases_by_pair) -> LineConversion:
    """Conversione della riga verso l'unità di confronto della voce (regola non rigida)."""
    if product is None:
        return LineConversion(None, False, None, "Riga non collegata a una voce")
    alias = alias_index.resolve(line.fornitore_id, product.id, line.codice_fornitore, line.descrizione)
    if alias is None:
        alias, ambiguous = _unique_pair_alias(aliases_by_pair, line.fornitore_id, product.id)
        if ambiguous:
            return LineConversion(None, False, product.comparison_unit,
                                  "Più collegamenti fornitore per la voce: conversione incerta")
    return line_conversion(
        product=product, alias=alias, unita_misura=line.unita_misura,
        descrizione=line.descrizione, strict_pack=False,
    )


def _without_outliers(lines: list[SpotLine]) -> list[SpotLine]:
    by_unit: dict[str, list[Decimal]] = {}
    for line in lines:
        by_unit.setdefault(normalized_unit(line.unita_misura), []).append(line.net)
    medians = {unit: Decimal(str(median(values))) for unit, values in by_unit.items()}
    return [
        line for line in lines
        if line.net > 0 and line.net >= medians[normalized_unit(line.unita_misura)] * OUTLIER_RATIO
    ]


def compute_spot_offers(
    lines: Iterable[SpotLine],
    products_by_sku: Mapping[str, Any],
    aliases: Iterable[Any],
    today: date,
) -> dict[tuple[str, int], dict]:
    """Offerta spot per (sku, fornitore) nel formato delle celle della matrice."""
    aliases = list(aliases)
    alias_index = AliasIndex(aliases)
    aliases_by_pair: dict[tuple[int, int], list] = {}
    for alias in aliases:
        aliases_by_pair.setdefault((alias.supplier_id, alias.product_id), []).append(alias)

    by_pair: dict[tuple[str, int], list[SpotLine]] = {}
    for line in lines:
        by_pair.setdefault((line.sku_interno, line.fornitore_id), []).append(line)

    offers: dict[tuple[str, int], dict] = {}
    for (sku, supplier_id), pair_lines in by_pair.items():
        usable = _without_outliers(pair_lines)
        if not usable:
            continue
        latest_by_location: dict[Optional[int], SpotLine] = {}
        for line in usable:
            current = latest_by_location.get(line.location_id)
            if current is None or (line.data_documento, line.riga_id) > (current.data_documento, current.riga_id):
                latest_by_location[line.location_id] = line
        product = products_by_sku.get(sku)
        candidates = []
        for line in latest_by_location.values():
            conversion = spot_conversion(line, product, alias_index, aliases_by_pair)
            candidates.append((line, conversion, conversion.unit_price(line.net)))
        comparable = [c for c in candidates if c[2] is not None]
        if comparable:
            line, conversion, unit_price = min(comparable, key=lambda c: (c[2], -c[0].data_documento.toordinal(), c[0].riga_id))
        else:
            line, conversion, unit_price = max(candidates, key=lambda c: (c[0].data_documento, c[0].riga_id))
        age_days = (today - line.data_documento).days
        offers[(sku, supplier_id)] = {
            "supplier_id": supplier_id,
            # Classifica solo sul prezzo convertito; None = fuori classifica.
            "unit_price_normalized": f"{unit_price:.4f}" if unit_price is not None else None,
            "comparison_reliable": unit_price is not None,
            "comparison_unit": getattr(product, "comparison_unit", None),
            "conversion_note": conversion.explanation,
            # Prezzo fatturato, nell'unità di fattura.
            "price": f"{line.net:.4f}",
            "uom": (line.unita_misura or "").strip() or None,
            "source_type": "spot",
            "invoice_date": line.data_documento.isoformat(),
            "invoice_line_id": line.riga_id,
            "location_id": line.location_id,
            "stale": age_days > SPOT_STALE_DAYS,
        }
    return offers
