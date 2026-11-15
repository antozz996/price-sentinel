"""Dashboard: analisi sprechi (variance-loss) e classifica efficienza dei locali.

Tutte e due partono dalla base comune services.purchase_lines, con le stesse
regole: solo acquisti pagati (niente note di credito TD04/TD08, niente omaggi),
filtro tenant, NOT EXISTS su skus_esclusi e righe_escluse_statistiche (una riga
esclusa non fa da minimo e non entra nemmeno nei totali), prezzo netto per unità
di fattura = pu x (1 - sconto/100).

Il minimo pagato si calcola per (voce, unità di fattura normalizzata): un prezzo
a cartone si confronta solo con cartoni, un kg solo con kg. Così una riga in
un'unità che non si sa convertire resta nella sua unità invece di mescolarsi.

Spreco di una riga = max(0, netto - riferimento) x quantità, con riferimento:
1. il listino del fornitore della riga valido alla data del documento, scelto
   come nel controllo anomalie (matching._get_listino_attivo) e riportato
   all'unità di fattura con il fattore di line_conversion (strict_pack): serve
   una conversione affidabile;
2. altrimenti il minimo pagato per (voce, unità di fattura) su tutto lo storico.
Lo spreco conta solo le fatture caricate da ANOMALY_CHECK_START in poi; la
risposta restituisce quella data, così l'intestazione dice il vero.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional, Sequence

from sqlalchemy import Numeric, case, cast, func, select
from sqlalchemy.orm import noload

from app.models.fatture import Fattura, RigaFattura, XMLRaw
from app.models.fornitori import Fornitore
from app.models.listino import ListinoMaster
from app.models.location import Location
from app.models.products import Product, SupplierProductAlias
from app.services.purchase_lines import (
    AliasIndex,
    ConversionKey,
    LineConversion,
    counts_for_average_sql,
    line_conversion,
    purchase_lines_select,
)

# A purchase within 5% of the minimum paid is "optimal" in the leaderboard.
EFFICIENCY_TOLERANCE = Decimal("1.05")
SOURCE_LISTINO = "listino"
SOURCE_MINIMUM = "minimo"
SOURCE_MIXED = "misto"


def _dec(value: Any) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal("0")


# ─────────────────────────────────────────────
# Listino valido alla data della riga
# ─────────────────────────────────────────────

def listino_valid_at(listini: Iterable[Any], doc_date: date, alias_id: Optional[int] = None) -> Optional[Any]:
    """Listino del fornitore valido alla data, con la regola di matching._get_listino_attivo.

    listini: righe listino_master dello stesso fornitore e della stessa voce.
    Prima i listini legati al collegamento della riga (alias_id): due validi lo
    stesso giorno sono ambigui e non se ne sceglie nessuno. Poi tutti: vale solo
    se ce n'è esattamente uno.
    """
    if doc_date is None:
        return None
    if isinstance(doc_date, datetime):
        doc_date = doc_date.date()
    valid = [
        item for item in listini
        if item.data_inizio_validita <= doc_date
        and (item.data_scadenza is None or item.data_scadenza >= doc_date)
    ]
    if alias_id is not None:
        exact = [item for item in valid if item.supplier_product_alias_id == alias_id]
        if len(exact) > 1:
            return None
        if exact:
            return exact[0]
    return valid[0] if len(valid) == 1 else None


def listino_price_per_invoice_unit(listino: Any, conversion: Optional[LineConversion]) -> Optional[Decimal]:
    """Prezzo di listino espresso nell'unità di fattura della riga; None se non confrontabile."""
    if listino is None or conversion is None or not conversion.reliable:
        return None
    if conversion.factor is None or conversion.factor <= 0:
        return None
    return _dec(listino.prezzo_pattuito) * conversion.factor


# ─────────────────────────────────────────────
# Aggregazione dello spreco (Python puro, testabile senza database)
# ─────────────────────────────────────────────

@dataclass(frozen=True)
class WasteLine:
    """Una riga d'acquisto pagata, nel periodo dello spreco."""

    riga_id: int
    sku_interno: str
    unita: str  # unità di fattura normalizzata (purchase_lines.normalized_unit)
    fornitore: str
    prodotto_nome: str
    quantita: Decimal
    netto_unitario: Decimal
    prezzo_listino: Optional[Decimal] = None  # listino nell'unità di fattura, se confrontabile


def line_reference(line: WasteLine, minimum: Optional[Decimal]) -> tuple[Optional[Decimal], Optional[str]]:
    """Riferimento della riga: listino valido se c'è, altrimenti minimo pagato."""
    if line.prezzo_listino is not None:
        return line.prezzo_listino, SOURCE_LISTINO
    if minimum is not None:
        return minimum, SOURCE_MINIMUM
    return None, None


def line_waste(line: WasteLine, minimum: Optional[Decimal]) -> Decimal:
    reference, _ = line_reference(line, minimum)
    if reference is None:
        return Decimal("0")
    return max(Decimal("0"), line.netto_unitario - reference) * line.quantita


def aggregate_waste(
    lines: Iterable[WasteLine],
    minimums: Mapping[tuple[str, str], Decimal],
    limit: Optional[int] = 10,
) -> list[dict]:
    """Spreco per (voce, unità di fattura), dal più alto.

    minimums: minimo pagato per (sku_interno, unità) su tutto lo storico.
    Fornitori elencati per spreco generato (chi pesa di più per primo).
    Prezzo medio e riferimento sono medie pesate sulle quantità.
    """
    groups: dict[tuple[str, str], list[WasteLine]] = defaultdict(list)
    for line in lines:
        groups[(line.sku_interno, line.unita)].append(line)

    results = []
    for key, group in groups.items():
        minimum = minimums.get(key)
        quantity = Decimal("0")
        amount = Decimal("0")
        waste = Decimal("0")
        reference_amount = Decimal("0")
        reference_quantity = Decimal("0")
        sources: set[str] = set()
        waste_by_supplier: dict[str, Decimal] = defaultdict(Decimal)
        for line in group:
            reference, source = line_reference(line, minimum)
            line_amount = max(Decimal("0"), line.netto_unitario - reference) * line.quantita if reference is not None else Decimal("0")
            quantity += line.quantita
            amount += line.netto_unitario * line.quantita
            waste += line_amount
            waste_by_supplier[line.fornitore] += line_amount
            if reference is not None:
                sources.add(source)
                reference_amount += reference * line.quantita
                reference_quantity += line.quantita
        if waste <= 0:
            continue
        suppliers = sorted(waste_by_supplier.items(), key=lambda item: (-item[1], item[0]))
        results.append({
            "sku_interno": key[0],
            "unita": key[1],
            "prodotto_nome": group[0].prodotto_nome or key[0],
            "fornitore_nome": ", ".join(name for name, _ in suppliers) or "ND",
            "numero_acquisti": len(group),
            "quantita_totale": float(quantity),
            "prezzo_minimo": float(minimum) if minimum is not None else None,
            "prezzo_riferimento": float(reference_amount / reference_quantity) if reference_quantity else None,
            "fonte_riferimento": (sources.pop() if len(sources) == 1 else SOURCE_MIXED) if sources else None,
            "prezzo_medio": float(amount / quantity) if quantity else 0.0,
            "spreco_totale": float(round(waste, 2)),
        })
    results.sort(key=lambda item: (-item["spreco_totale"], item["sku_interno"], item["unita"]))
    return results[:limit] if limit is not None else results


# ─────────────────────────────────────────────
# Query
# ─────────────────────────────────────────────

def paid_purchase_lines(user):
    """Righe d'acquisto pagate con voce: base comune senza note di credito né omaggi."""
    return purchase_lines_select(user, require_sku=True, include_credit_notes=False).where(
        counts_for_average_sql(RigaFattura, Fattura.tipo_documento)
    )


def check_start_date(check_start: Optional[datetime]) -> Optional[str]:
    if check_start is None:
        return None
    return (check_start.date() if isinstance(check_start, datetime) else check_start).isoformat()


async def load_variance_loss(db, user, check_start: Optional[datetime], limit: int = 10) -> dict:
    """Prime voci per spreco dal check_start: {"periodo_dal": "AAAA-MM-GG" | None, "righe": [...]}."""
    scope = paid_purchase_lines(user)
    if check_start is not None:
        scope = scope.where(
            Fattura.xml_raw_id.in_(select(XMLRaw.id).where(XMLRaw.data_ricezione >= check_start))
        )
    scope_sq = scope.subquery("righe_periodo")
    rows = (await db.execute(select(scope_sq))).all()
    periodo = check_start_date(check_start)
    if not rows:
        return {"periodo_dal": periodo, "righe": []}

    # Minimum paid per (item, invoice unit) over the whole history, same row rules.
    history = paid_purchase_lines(user).subquery("righe_storico")
    minimums = {
        (sku, unit): _dec(value)
        for sku, unit, value in (await db.execute(
            select(history.c.sku_interno, history.c.unita, func.min(history.c.netto_unitario))
            .where(history.c.sku_interno.in_(select(scope_sq.c.sku_interno).distinct()))
            .group_by(history.c.sku_interno, history.c.unita)
        )).all()
    }

    skus = {row.sku_interno for row in rows}
    supplier_ids = {row.fornitore_id for row in rows}
    product_ids = {row.product_id for row in rows if row.product_id is not None}
    products: dict[int, Product] = {}
    if product_ids:
        products = {
            p.id: p for p in (await db.scalars(
                select(Product).options(noload("*")).where(Product.id.in_(product_ids))
            )).all()
        }
    aliases = AliasIndex((await db.scalars(
        select(SupplierProductAlias).options(noload("*")).where(SupplierProductAlias.supplier_id.in_(supplier_ids))
    )).all())
    listini: dict[tuple[int, str], list[ListinoMaster]] = defaultdict(list)
    for item in (await db.scalars(
        select(ListinoMaster).options(noload("*")).where(
            ListinoMaster.fornitore_id.in_(supplier_ids), ListinoMaster.sku_interno.in_(skus)
        ).order_by(ListinoMaster.data_inizio_validita.desc(), ListinoMaster.id.desc())
    )).all():
        listini[(item.fornitore_id, item.sku_interno)].append(item)
    suppliers = dict((await db.execute(
        select(Fornitore.id, Fornitore.nome_azienda).where(Fornitore.id.in_(supplier_ids))
    )).all())

    lines = build_waste_lines(rows, products, aliases, listini, suppliers)
    return {"periodo_dal": periodo, "righe": aggregate_waste(lines, minimums, limit)}


def build_waste_lines(
    rows: Sequence[Any],
    products: Mapping[int, Product],
    aliases: AliasIndex,
    listini: Mapping[tuple[int, str], Sequence[Any]],
    suppliers: Mapping[int, str],
) -> list[WasteLine]:
    """Righe di purchase_lines_select -> WasteLine, con il listino valido già nell'unità di fattura."""
    conversions: dict[tuple[ConversionKey, Optional[str]], LineConversion] = {}
    lines = []
    for row in rows:
        product = products.get(row.product_id) if row.product_id is not None else None
        alias = aliases.resolve(row.fornitore_id, row.product_id, row.codice_fornitore, row.descrizione)
        listino = listino_valid_at(
            listini.get((row.fornitore_id, row.sku_interno), ()), row.data_documento,
            alias.id if alias is not None else None,
        )
        listino_price = None
        if listino is not None and product is not None:
            key = (
                ConversionKey(row.fornitore_id, row.product_id, row.codice_fornitore, row.descrizione, row.unita_misura),
                listino.unita_misura,
            )
            if key not in conversions:
                conversions[key] = line_conversion(
                    product=product, alias=alias, unita_misura=row.unita_misura,
                    descrizione=row.descrizione, target_unit=listino.unita_misura,
                )
            listino_price = listino_price_per_invoice_unit(listino, conversions[key])
        lines.append(WasteLine(
            riga_id=row.riga_id,
            sku_interno=row.sku_interno,
            unita=row.unita,
            fornitore=suppliers.get(row.fornitore_id) or "ND",
            prodotto_nome=(product.canonical_name if product is not None else None) or row.descrizione or row.sku_interno,
            quantita=_dec(row.quantita),
            netto_unitario=_dec(row.netto_unitario),
            prezzo_listino=listino_price,
        ))
    return lines


def efficiency_leaderboard_select(user):
    """Classifica: quota di acquisti entro il 5% del minimo pagato per (voce, unità di fattura).

    Stessa base dello spreco su tutto lo storico; spareggio su numero di acquisti
    e poi id del locale, così l'ordine non cambia da una chiamata all'altra.
    """
    base = paid_purchase_lines(user).subquery("righe")
    minimum = func.min(base.c.netto_unitario).over(partition_by=(base.c.sku_interno, base.c.unita))
    scored = select(
        base.c.location_id,
        case((base.c.netto_unitario <= minimum * EFFICIENCY_TOLERANCE, 1), else_=0).label("ottimale"),
    ).subquery("acquisti")
    totali = func.count().label("totali")
    ottimali = func.sum(scored.c.ottimale).label("ottimali")
    score = func.round(cast(func.sum(scored.c.ottimale), Numeric) * 100 / func.count(), 2).label("score")
    return (
        select(
            scored.c.location_id,
            func.coalesce(Location.nome_struttura, "Sede Non Assegnata").label("nome_struttura"),
            totali,
            ottimali,
            score,
        )
        .select_from(scored)
        .outerjoin(Location, Location.id == scored.c.location_id)
        .group_by(scored.c.location_id, Location.nome_struttura)
        .order_by(score.desc(), totali.desc(), scored.c.location_id.asc().nulls_last())
    )
