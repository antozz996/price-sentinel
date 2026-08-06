"""Infer product/supplier relevance from real commercial evidence."""

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fatture import Fattura, RigaFattura
from app.models.listino import ListinoMaster
from app.models.products import Product, SupplierProductAlias
from app.models.purchase_policy import ProductSupplierAssessment


@dataclass(frozen=True)
class SupplierCatalogScope:
    direct_pairs: set[tuple[int, int]]
    categories_by_supplier: dict[int, set[str]]

    def eligible_supplier_ids(
        self,
        *,
        product_id: int,
        category: str | None,
        supplier_ids: set[int],
    ) -> set[int]:
        normalized_category = (category or "").strip().casefold()
        return {
            supplier_id
            for supplier_id in supplier_ids
            if (product_id, supplier_id) in self.direct_pairs
            or (
                normalized_category
                and normalized_category
                in self.categories_by_supplier.get(supplier_id, set())
            )
        }


async def load_supplier_catalog_scope(
    db: AsyncSession,
    *,
    supplier_ids: set[int] | None = None,
) -> SupplierCatalogScope:
    """Use aliases, listini, invoices and explicit assessments as scope evidence."""
    statements = [
        select(Product.id, Product.category, SupplierProductAlias.supplier_id)
        .join(SupplierProductAlias, SupplierProductAlias.product_id == Product.id)
        .where(Product.is_active.is_(True), SupplierProductAlias.status == "approved"),
        select(Product.id, Product.category, ListinoMaster.fornitore_id)
        .join(ListinoMaster, ListinoMaster.sku_interno == Product.sku_interno)
        .where(Product.is_active.is_(True), Product.sku_interno.is_not(None)),
        select(Product.id, Product.category, Fattura.fornitore_id)
        .join(RigaFattura, RigaFattura.sku_interno == Product.sku_interno)
        .join(Fattura, Fattura.id == RigaFattura.fattura_id)
        .where(Product.is_active.is_(True), Product.sku_interno.is_not(None)),
        select(Product.id, Product.category, ProductSupplierAssessment.supplier_id)
        .join(ProductSupplierAssessment, ProductSupplierAssessment.product_id == Product.id)
        .where(Product.is_active.is_(True), ProductSupplierAssessment.is_active.is_(True)),
    ]
    if supplier_ids:
        supplier_columns = (
            SupplierProductAlias.supplier_id,
            ListinoMaster.fornitore_id,
            Fattura.fornitore_id,
            ProductSupplierAssessment.supplier_id,
        )
        statements = [
            statement.where(supplier_column.in_(supplier_ids))
            for statement, supplier_column in zip(statements, supplier_columns)
        ]

    direct_pairs: set[tuple[int, int]] = set()
    categories_by_supplier: dict[int, set[str]] = defaultdict(set)
    for statement in statements:
        rows = (await db.execute(statement.distinct())).all()
        for product_id, category, supplier_id in rows:
            direct_pairs.add((product_id, supplier_id))
            normalized_category = (category or "").strip().casefold()
            if normalized_category:
                categories_by_supplier[supplier_id].add(normalized_category)

    return SupplierCatalogScope(
        direct_pairs=direct_pairs,
        categories_by_supplier=dict(categories_by_supplier),
    )
