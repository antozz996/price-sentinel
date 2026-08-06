"""Focused, database-free tests for bulk product classification updates."""

import asyncio
import json

from fastapi import HTTPException

from app.api.v1.product_identity import (
    ProductBulkClassificationUpdate,
    bulk_update_product_classification,
)
from app.models.products import Product


class FakeScalars:
    def __init__(self, products):
        self.products = products

    def all(self):
        return self.products


class FakeResult:
    def __init__(self, products):
        self.products = products

    def scalars(self):
        return FakeScalars(self.products)


class FakeSession:
    def __init__(self, *result_sets):
        self.result_sets = list(result_sets)
        self.flush_count = 0

    async def execute(self, _statement):
        return FakeResult(self.result_sets.pop(0))

    async def flush(self):
        self.flush_count += 1


def product(product_id: int, category="old", subcategory="old-sub"):
    return Product(
        id=product_id,
        canonical_name=f"Product {product_id}",
        comparison_unit="piece",
        category=category,
        subcategory=subcategory,
    )


async def run_tests():
    results = []

    products = [product(1), product(2)]
    db = FakeSession(products, products)
    response = await bulk_update_product_classification(
        ProductBulkClassificationUpdate(
            product_ids=[1, 2, 2],
            category="  beverage  ",
            subcategory=" soft drink ",
        ),
        db=db,
        _admin=object(),
    )
    assert response["updated_count"] == 2
    assert all(item.category == "beverage" for item in products)
    assert all(item.subcategory == "soft drink" for item in products)
    assert db.flush_count == 1
    results.append("set category and subcategory atomically")

    products = [product(3, category="food", subcategory="snack")]
    db = FakeSession(products, products)
    await bulk_update_product_classification(
        ProductBulkClassificationUpdate(product_ids=[3], subcategory=None),
        db=db,
        _admin=object(),
    )
    assert products[0].category == "food"
    assert products[0].subcategory is None
    results.append("clear one field without changing the other")

    try:
        await bulk_update_product_classification(
            ProductBulkClassificationUpdate(product_ids=[4]),
            db=FakeSession([product(4)]),
            _admin=object(),
        )
        raise AssertionError("empty update accepted")
    except HTTPException as error:
        assert error.status_code == 422
    results.append("reject empty update")

    existing = product(5)
    db = FakeSession([existing])
    try:
        await bulk_update_product_classification(
            ProductBulkClassificationUpdate(product_ids=[5, 999], category="new"),
            db=db,
            _admin=object(),
        )
        raise AssertionError("missing product accepted")
    except HTTPException as error:
        assert error.status_code == 404
        assert existing.category == "old"
        assert db.flush_count == 0
    results.append("reject missing IDs before modifying records")

    print(json.dumps({"status": "PASS", "tests": len(results), "results": results}, indent=2))


asyncio.run(run_tests())
