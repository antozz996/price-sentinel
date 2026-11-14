"""Forma canonica dell'unità di confronto nei salvataggi da import (canonical_unit, modalità tollerante).

python -m unittest discover -s tests -p 'test_comparison_unit_catalogue.py' -v   (da backend/, PYTHONPATH=.)
"""
import os
import unittest
from decimal import Decimal

# Placeholder settings: these tests never open a database connection.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from app.models.products import Product  # noqa: E402
from app.services.matching import normalize_price_for_comparison  # noqa: E402
from app.services.normalization import canonical_unit  # noqa: E402


class LenientCanonicalUnitTest(unittest.TestCase):
    def test_spellings_of_the_four_units(self):
        cases = {
            "piece": "Pz", "PZ": "Pz", "pz": "Pz", "Pezzi": "Pz",
            "Ct": "CT", "ct": "CT", "CT": "CT", "cartone": "CT",
            "kg": "Kg", "KG": "Kg", "K.": "Kg", "KGM": "Kg",
            "LT": "Lt", "lt": "Lt", "L": "Lt", "litro": "Lt",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(canonical_unit(raw), expected)

    def test_empty_becomes_null(self):
        for raw in (None, "", "   "):
            self.assertIsNone(canonical_unit(raw))

    def test_other_units_are_kept(self):
        for raw in ("BT", "conf", "CF", "COL"):
            with self.subTest(raw=raw):
                self.assertEqual(canonical_unit(raw), raw)


class ProductStoresCatalogueUnitTest(unittest.TestCase):
    def test_product_constructor_and_assignment(self):
        product = Product(canonical_name="MINI PANINO", comparison_unit="piece")
        self.assertEqual(product.comparison_unit, "Pz")
        product.comparison_unit = "Ct"
        self.assertEqual(product.comparison_unit, "CT")
        product.comparison_unit = "BT"
        self.assertEqual(product.comparison_unit, "BT")
        product.comparison_unit = ""
        self.assertIsNone(product.comparison_unit)

    def test_comparison_is_unchanged_by_the_new_spelling(self):
        # Same result before (raw spelling) and after (catalogue spelling).
        for raw in ("piece", "Ct", "Lt", "Kg"):
            with self.subTest(raw=raw):
                before = normalize_price_for_comparison(Decimal("25.90"), Decimal("1"), "CT",
                                                        Product(comparison_unit=None, unit_count=100), None,
                                                        target_comparison_unit=raw)
                after = normalize_price_for_comparison(Decimal("25.90"), Decimal("1"), "CT",
                                                       Product(comparison_unit=raw, unit_count=100), None)
                self.assertEqual(before.comparison_unit, after.comparison_unit)
                self.assertEqual(before.normalized_unit_price, after.normalized_unit_price)
                self.assertEqual(before.reliable, after.reliable)


if __name__ == "__main__":
    unittest.main()
