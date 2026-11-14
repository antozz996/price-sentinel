"""resolve_invoice_line_product: a description linked to two products must not pick one by row order.

Real case (MELIUS, 14/11/2026): links 2567 (code VCUBVIT, product 991 Polish cuberoll) and 2633
(code VREAIRLB, product 1057 Irish cuberoll) both carry "CUBEROLL B.ADULTO IRLANDA FR.S/V".
Destination in the repo: backend/tests/test_matching_ambiguous_description.py
"""
import asyncio
import os
import unittest
from types import SimpleNamespace

# Placeholder settings: these tests never open a database connection.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from app.services.matching import resolve_invoice_line_product  # noqa: E402
from app.services.normalization import normalize_text  # noqa: E402

IRISH = "CUBEROLL B.ADULTO IRLANDA FR.S/V"
POLISH = "CUBEROLL VACC MANZ.PRUSS POL.2,5+ MAREZZ."


def product(pid, name):
    return SimpleNamespace(id=pid, sku_interno=f"SKU-{pid}", canonical_name=name, is_active=True, brand=None,
                           category="Food", volume_ml=None, weight_g=None, unit_count=1, comparison_unit="Kg",
                           container_type=None)


def link(aid, pid, code, description):
    return SimpleNamespace(id=aid, product_id=pid, supplier_code=code, raw_description=description,
                           normalized_description=normalize_text(description), status="approved", ean=None)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _Db:
    """resolve_invoice_line_product runs two queries: active products, then the supplier's links."""

    def __init__(self, products, links):
        self._answers = [products, links]

    async def execute(self, _stmt):
        return _Result(self._answers.pop(0))


def resolve(links, description, code=None, products=None):
    products = products or [product(991, POLISH), product(1057, IRISH)]
    return asyncio.run(resolve_invoice_line_product(_Db(products, links), 9, description, supplier_code=code))


class AmbiguousDescriptionTest(unittest.TestCase):
    def test_same_result_whatever_the_link_order(self):
        polish_link = link(2567, 991, "VCUBVIT", IRISH)  # wrong wording on the Polish product
        irish_link = link(2633, 1057, "VREAIRLB", IRISH)
        first = resolve([polish_link, irish_link], IRISH, code="NEWCODE")
        second = resolve([irish_link, polish_link], IRISH, code="NEWCODE")
        self.assertEqual(first["product_id"], second["product_id"])
        # the line is written exactly like the catalog name of 1057, which the supplier is linked to
        self.assertEqual(first["product_id"], 1057)
        self.assertNotEqual(first["supplier_alias_id"], 2567)

    def test_unambiguous_description_still_matches(self):
        result = resolve([link(2633, 1057, "VREAIRLB", IRISH)], IRISH, code="NEWCODE",
                         products=[product(991, POLISH), product(1057, "CUBEROLL IRLANDA")])
        self.assertEqual(result["product_id"], 1057)
        self.assertEqual(result["supplier_alias_id"], 2633)
        self.assertEqual(result["score"], 98.0)

    def test_code_wins_over_ambiguous_description(self):
        links = [link(2633, 1057, "VREAIRLB", IRISH), link(2567, 991, "VCUBVIT", IRISH)]
        result = resolve(links, IRISH, code="VCUBVIT")
        self.assertEqual(result["product_id"], 991)
        self.assertEqual(result["score"], 100.0)

    def test_ambiguous_description_without_catalog_name_is_not_auto_matched_by_alias(self):
        generic = "CUBEROLL MANZETTA PRUSSIANA FR.S/V"
        links = [link(1, 208, "A", generic), link(2, 2405, "B", generic)]
        result = resolve(links, generic, code="NEWCODE",
                         products=[product(208, "MANZETTA PRUSSIANA"), product(2405, "CUBEROLL ARGENTINA")])
        self.assertIsNone(result["supplier_alias_id"])


if __name__ == "__main__":
    unittest.main()
