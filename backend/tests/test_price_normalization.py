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


class KilogramUnitTest(unittest.TestCase):
    """normalize_text() turns "kg" into "chilogrammi": kilograms must not fall back to "piece"."""

    def test_product_in_kg_compares_per_kg(self):
        result = normalize_price_for_comparison(Decimal("1.00"), Decimal("1"), "KG", product("Kg"), None)
        self.assertTrue(result.reliable)
        self.assertEqual(result.comparison_unit, "kg")

    def test_weighed_pack_is_converted_to_price_per_kg(self):
        pack = SimpleNamespace(pack_qty=1, raw_description="FRAGOLE", volume_ml=None, weight_g=250)
        result = normalize_price_for_comparison(Decimal("3.00"), Decimal("1"), "conf", product("Kg"), pack)
        self.assertTrue(result.reliable)
        self.assertEqual(result.comparison_unit, "kg")
        self.assertEqual(result.normalized_unit_price, Decimal("12"))


class KilogramInvoiceCodeTest(unittest.TestCase):
    """DAC writes "K." for the kilogram; FatturaPA files may carry the UN/ECE code "KGM"."""

    def test_kilogram_codes_compare_per_kg(self):
        for uom in ("K.", "k.", "K", "KGM", "Kgs"):
            result = normalize_price_for_comparison(Decimal("19.30"), Decimal("1"), uom, product("Kg"), None)
            self.assertTrue(result.reliable, uom)
            self.assertEqual(result.comparison_unit, "kg", uom)
            self.assertEqual(result.normalized_unit_price, Decimal("19.30"), uom)

    def test_weight_in_the_description_is_not_applied_to_a_price_per_kg(self):
        line = SimpleNamespace(pack_qty=None, raw_description="EDAMER DANUBIA X KG 2,70", volume_ml=None, weight_g=None)
        result = normalize_price_for_comparison(Decimal("4.49"), Decimal("2"), "K.", product("Kg"), line)
        self.assertTrue(result.reliable)
        self.assertEqual(result.normalized_unit_price, Decimal("4.49"))

    def test_kilogram_code_is_not_a_price_per_piece(self):
        result = normalize_price_for_comparison(Decimal("19.30"), Decimal("1"), "K.", product("Pz"), None)
        self.assertFalse(result.reliable)

    def test_price_list_unit_k_dot_means_kg(self):
        result = normalize("4.49", "KG", "K.")
        self.assertTrue(result.reliable)
        self.assertEqual(result.comparison_unit, "kg")

    def test_other_units_are_unchanged(self):
        from app.services.normalization import normalize_uom
        for raw, expected in (("KG", "chilogrammi"), ("CT", "cartone"), ("PZ", "pezzi"), ("N.", "n."), ("", "")):
            self.assertEqual(normalize_uom(raw), expected, raw)


class WeightPricePerPieceTest(unittest.TestCase):
    """A price per kg/litre on a product compared per piece must not pass as a price per piece."""

    def test_price_per_kg_is_not_a_price_per_piece(self):
        for uom in ("KG", "kg", "LT", "L", "GR"):
            result = normalize_price_for_comparison(Decimal("25.90"), Decimal("1"), uom, product("Pz"), None)
            self.assertFalse(result.reliable, uom)

    def test_piece_and_pack_prices_stay_reliable(self):
        for uom in ("PZ", "NR", "BT", None):
            result = normalize_price_for_comparison(Decimal("1.32"), Decimal("1"), uom, product("Pz"), None)
            self.assertTrue(result.reliable, uom)


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


class PackFactorTest(unittest.TestCase):
    """fattore_confezione: one invoice unit holds N price-list units (invoice lines only)."""

    @staticmethod
    def line(price, uom=None, description="VASCHETTA OVALE IN POLPA 650ML PZ. 500"):
        return SimpleNamespace(prezzo_unitario_fatturato=Decimal(price), sconto_percentuale=0, quantita=Decimal("2"),
                               unita_misura_fattura=uom, descrizione_fornitore_raw=description)

    @staticmethod
    def product_row(comparison_unit="CT"):
        from app.models.products import Product
        return Product(comparison_unit=comparison_unit, unit_count=1)

    @staticmethod
    def factor_alias(factor):
        return SimpleNamespace(pack_qty=None, fattore_confezione=factor, raw_description="", volume_ml=None, weight_g=None)

    def test_carton_of_500_compared_with_price_list_per_50(self):
        result = normalize_price_for_comparison(self.line("52.80"), self.product_row(), alias=self.factor_alias(Decimal("10")),
                                                target_comparison_unit="CT")
        self.assertTrue(result.reliable)
        self.assertEqual(result.normalized_unit_price, Decimal("5.28"))

    def test_bag_of_5_kg_compared_with_price_list_per_kg(self):
        result = normalize_price_for_comparison(self.line("12.14", "PZ", "RISO SCOTTI 5 KG"), self.product_row("Kg"),
                                                alias=self.factor_alias(Decimal("5")), target_comparison_unit="Kg")
        self.assertTrue(result.reliable)
        self.assertEqual(result.comparison_unit, "kg")
        self.assertEqual(round(result.normalized_unit_price, 3), Decimal("2.428"))

    def test_without_factor_behaviour_is_unchanged(self):
        result = normalize_price_for_comparison(self.line("52.80"), self.product_row(), alias=self.factor_alias(None),
                                                target_comparison_unit="CT")
        self.assertEqual(result.normalized_unit_price, Decimal("52.80"))

    def test_factor_is_ignored_for_price_list_prices(self):
        result = normalize_price_for_comparison(Decimal("5.28"), Decimal("1"), "CT", product("CT"), self.factor_alias(Decimal("10")))
        self.assertEqual(result.normalized_unit_price, Decimal("5.28"))


if __name__ == "__main__":
    unittest.main()
