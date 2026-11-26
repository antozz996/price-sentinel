"""«Package» nelle fatture elettroniche in inglese è una confezione (Illy: 6X1KG ILLYCREMA a cartone da 6)."""
import unittest
from decimal import Decimal
from types import SimpleNamespace

from app.models.products import Product
from app.services.matching import normalize_price_for_comparison


class PackageUnitTest(unittest.TestCase):
    def test_package_is_a_box_of_pack_qty_pieces(self):
        product = Product(canonical_name="ILLYCREMA 1 KG", comparison_unit="Pz", unit_count=1)
        alias = SimpleNamespace(pack_qty=6, raw_description="6X1KG ILLYCREMA", fattore_confezione=None,
                                volume_ml=None, weight_g=None)
        result = normalize_price_for_comparison(Decimal("179.58"), Decimal("3"), "Package", product, alias, strict_pack=True)
        self.assertTrue(result.reliable)
        self.assertEqual(result.normalized_unit_price, Decimal("29.93"))
        self.assertEqual(result.listino_units_per_invoice_unit, Decimal("6"))

    def test_package_without_known_pack_is_not_guessed(self):
        product = Product(canonical_name="ILLYCREMA 1 KG", comparison_unit="Pz", unit_count=1)
        alias = SimpleNamespace(pack_qty=None, raw_description="ILLYCREMA", fattore_confezione=None,
                                volume_ml=None, weight_g=None)
        result = normalize_price_for_comparison(Decimal("179.58"), Decimal("3"), "Package", product, alias, strict_pack=True)
        self.assertFalse(result.reliable)


if __name__ == "__main__":
    unittest.main()
