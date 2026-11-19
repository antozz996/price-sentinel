"""Listino sempre aperto: chi sarà il fornitore più conveniente a una data (anche futura).

Prezzo a una data = righe di listino valide quel giorno, con sopra le modifiche già
programmate che a quella data saranno entrate (aumenti, chiusure «non lo tratto più»).
Le modifiche sospese no: aspettano l'ufficio. Il confronto è lo stesso della scelta
automatica (cheapest_comparable_listino): prezzo nell'unità di confronto della voce,
le righe non confrontabili con certezza restano fuori.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.models.listino import ListinoMaster
from app.models.products import Product, SupplierProductAlias
from app.models.supplier_price_link import STATO_PROGRAMMATO, TIPO_NON_TRATTATO, SupplierPriceChange, offer_key
from app.services.purchase_recommendation import comparable_listino_price


@dataclass
class Forecast:
    """Prezzi confrontabili di ogni fornitore per una voce, a una data."""
    giorno: date
    prezzi: dict[int, Decimal] = field(default_factory=dict)   # fornitore_id -> prezzo nell'unità di confronto
    unita_confronto: str | None = None

    @property
    def migliore(self) -> int | None:
        if not self.prezzi:
            return None
        return min(self.prezzi.items(), key=lambda item: (item[1], item[0]))[0]


_COLUMNS = [column.key for column in ListinoMaster.__table__.columns]


def _as_row(row, prezzo=None):
    """Copia staccata della riga (mai modificare la riga del database: verrebbe salvata)."""
    copy = SimpleNamespace(**{name: getattr(row, name) for name in _COLUMNS if hasattr(row, name)})
    if prezzo is not None:
        copy.prezzo_pattuito = prezzo
    return copy


def price_day(data_consegna: str | None, today: date) -> date:
    """Giorno a cui leggere i prezzi di un ordine: la consegna, mai prima di oggi."""
    try:
        day = date.fromisoformat((data_consegna or "").strip()[:10])
    except ValueError:
        return today
    return max(day, today)


async def with_scheduled(db: AsyncSession, rows, day: date) -> list:
    """Le righe di listino come saranno quel giorno, con le modifiche già programmate."""
    rows = list(rows)
    if not rows:
        return []
    changes = (await db.execute(select(SupplierPriceChange).where(
        SupplierPriceChange.sku_interno.in_({row.sku_interno for row in rows}),
        SupplierPriceChange.stato == STATO_PROGRAMMATO,
        SupplierPriceChange.decorrenza <= day,
    ))).scalars().all()
    return apply_scheduled(rows, changes, day)


def apply_scheduled(rows, changes, day: date) -> list:
    """Le righe come saranno quel giorno: prezzo nuovo per le modifiche programmate già
    entrate a quella data, riga tolta se il fornitore non tratta più il prodotto."""
    due = {(c.fornitore_id, c.chiave_offerta): c for c in changes
           if c.stato == STATO_PROGRAMMATO and c.decorrenza <= day}
    result = []
    for row in rows:
        change = due.get((row.fornitore_id, offer_key(row.sku_interno, row.supplier_product_alias_id)))
        if change is None:
            result.append(_as_row(row))
        elif change.tipo == TIPO_NON_TRATTATO:
            continue
        elif change.prezzo_nuovo is not None:
            result.append(_as_row(row, Decimal(str(change.prezzo_nuovo))))
        else:
            result.append(_as_row(row))
    return result


def forecast_for_product(rows, product, aliases_by_id: dict, day: date) -> Forecast:
    """Prezzo confrontabile più basso di ogni fornitore (tra le sue varianti) per una voce."""
    forecast = Forecast(giorno=day, unita_confronto=getattr(product, "comparison_unit", None))
    for row in rows:
        price = comparable_listino_price(row, product, aliases_by_id.get(row.supplier_product_alias_id))
        if price is None:
            continue
        current = forecast.prezzi.get(row.fornitore_id)
        if current is None or price < current:
            forecast.prezzi[row.fornitore_id] = price
    return forecast


async def forecast_on(db: AsyncSession, skus: set[str], day: date) -> dict[str, Forecast]:
    """Per ogni voce: i prezzi confrontabili di tutti i fornitori a quella data."""
    if not skus:
        return {}
    rows = (await db.execute(select(ListinoMaster).options(noload("*")).where(
        ListinoMaster.sku_interno.in_(skus),
        ListinoMaster.data_inizio_validita <= day,
        or_(ListinoMaster.data_scadenza.is_(None), ListinoMaster.data_scadenza >= day),
    ))).scalars().all()
    changes = (await db.execute(select(SupplierPriceChange).where(
        SupplierPriceChange.sku_interno.in_(skus),
        SupplierPriceChange.stato == STATO_PROGRAMMATO,
        SupplierPriceChange.decorrenza <= day,
    ))).scalars().all()
    products = {p.sku_interno: p for p in (await db.execute(select(Product).options(noload("*")).where(
        Product.sku_interno.in_(skus)))).scalars().all()}
    alias_ids = {row.supplier_product_alias_id for row in rows if row.supplier_product_alias_id}
    aliases = {a.id: a for a in (await db.execute(select(SupplierProductAlias).options(noload("*")).where(
        SupplierProductAlias.id.in_(alias_ids)))).scalars().all()} if alias_ids else {}
    by_sku: dict[str, list] = {}
    for row in apply_scheduled(rows, changes, day):
        by_sku.setdefault(row.sku_interno, []).append(row)
    return {sku: forecast_for_product(by_sku.get(sku, []), products.get(sku), aliases, day)
            for sku in skus if sku in products}
