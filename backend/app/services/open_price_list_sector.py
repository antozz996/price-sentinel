"""Listino sempre aperto: la lista di prodotti del settore, uguale per tutti i fornitori.

Tutti i fornitori abilitati alla stessa categoria (e agli stessi reparti, dove la
categoria è divisa in reparti) vedono la stessa lista, anche i prodotti che non
hanno ancora a listino: così si confrontano sugli stessi articoli. Stessa regola
dei moduli prezzi (supplier_price_forms.create_form_request).

Nella lista entrano i prodotti che usiamo davvero: con un prezzo valido oggi da
qualche fornitore o comprati negli ultimi 12 mesi.
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.api.v1.supplier_price_forms import _enabled_sections
from app.models.listino import ListinoMaster
from app.models.products import Product
from app.models.purchase_policy import SupplierCategoryCapability


def _norm(value: str | None) -> str:
    return (value or "").strip().casefold()


def sector_categories(explicit: list[tuple[str, bool]], own_categories: set[str]) -> set[str]:
    """Le categorie abilitate per il fornitore; se l'ufficio non ne ha indicate, quelle dei suoi prodotti."""
    enabled = {_norm(c) for c, on in explicit if on and _norm(c)}
    disabled = {_norm(c) for c, on in explicit if not on}
    return (enabled or {_norm(c) for c in own_categories if _norm(c)}) - disabled


def in_sections(product, sections: set[str] | None, own_skus: set[str]) -> bool:
    """Dove la categoria è divisa in reparti, solo i reparti abilitati (un macellaio non vede la frutta).
    Un prodotto non ancora assegnato a un reparto resta a chi lo vende già."""
    if sections is None:
        return True
    sub = _norm(product.subcategory)
    return sub in sections if sub else product.sku_interno in own_skus


async def sector_products(db: AsyncSession, supplier_id: int, own_skus: set[str], today) -> list[Product]:
    explicit = (await db.execute(select(SupplierCategoryCapability.category, SupplierCategoryCapability.enabled)
                                 .where(SupplierCategoryCapability.supplier_id == supplier_id))).all()
    own_categories = set((await db.scalars(select(Product.category).where(
        Product.sku_interno.in_(own_skus)))).all()) if own_skus else set()
    categories = sector_categories(explicit, own_categories)
    if not categories:
        return []
    products = (await db.execute(select(Product).options(noload("*")).where(
        Product.is_active.is_(True), Product.sku_interno.is_not(None),
        func.lower(func.btrim(Product.category)).in_(categories),
    ))).scalars().all()
    sections = {category: await _enabled_sections(db, supplier_id, category) for category in categories}
    products = [p for p in products if in_sections(p, sections.get(_norm(p.category)), own_skus)]
    return products


async def skus_in_use(db: AsyncSession, skus: set[str], today) -> set[str]:
    """Prodotti con un prezzo valido oggi da almeno un fornitore."""
    if not skus:
        return set()
    return set((await db.scalars(select(ListinoMaster.sku_interno).where(
        ListinoMaster.sku_interno.in_(skus),
        ListinoMaster.data_inizio_validita <= today,
        (ListinoMaster.data_scadenza.is_(None)) | (ListinoMaster.data_scadenza >= today),
    ).distinct())).all())
