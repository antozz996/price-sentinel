import os
import unittest
from decimal import Decimal
from types import SimpleNamespace

# Placeholder settings: these tests never open a database connection.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from app.services.matching import normalize_price_for_comparison


def product(comparison_unit="Pz", unit_count=1):
    return SimpleNamespace(comparison_unit=comparison_unit, unit_count=unit_count, volume_ml=None, weight_g=None)


def alias(pack_qty=None, description="Calice 113 ml 54 pezzi"):
    return SimpleNamespace(pack_qty=pack_qty, raw_description=description, volume_ml=None, weight_g=None)


def normalize(price, uom, target, pack_qty=None, comparison_unit="Pz"):
    return normalize_price_for_comparison(
        Decimal(price), Decimal("1"), uom, product(comparison_unit), alias(pack_qty), target_comparison_unit=target,
    )


class PackUnitTest(unittest.TestCase):
    def test_pack_price_matches_a_pack_price_list(self):
        result = normalize("50.09", "CF", "CF", pack_qty=54)
        self.assertTrue(result.reliable)
        self.assertEqual(result.comparison_unit, "box")
        self.assertEqual(result.normalized_unit_price, Decimal("50.09"))

    def test_pack_price_is_split_when_compared_per_piece(self):
        result = normalize("50.09", "CF", "PZ", pack_qty=54)
        self.assertTrue(result.reliable)
        self.assertEqual(result.comparison_unit, "piece")
        self.assertEqual(round(result.normalized_unit_price, 4), Decimal("0.9276"))

    def test_piece_price_is_scaled_when_the_price_list_is_per_pack(self):
        result = normalize("0.96", "PZ", "CF", pack_qty=54)
        self.assertTrue(result.reliable)
        self.assertEqual(result.normalized_unit_price, Decimal("51.84"))

    def test_cnf_is_also_a_pack(self):
        result = normalize("6.00", "CNF", "PZ", pack_qty=50)
        self.assertTrue(result.reliable)
        self.assertEqual(round(result.normalized_unit_price, 4), Decimal("0.1200"))

    def test_pack_without_known_size_keeps_its_price(self):
        result = normalize("12.00", "CF", "PZ")
        self.assertTrue(result.reliable)
        self.assertEqual(result.normalized_unit_price, Decimal("12.00"))

    def test_carton_behaviour_is_unchanged(self):
        result = normalize("26.23", "CT", "BT", pack_qty=24)
        self.assertTrue(result.reliable)
        self.assertEqual(round(result.normalized_unit_price, 4), Decimal("1.0929"))


if __name__ == "__main__":
    unittest.main()
