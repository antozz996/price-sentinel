"""Listino sempre aperto: stessa lista per tutti i fornitori dello stesso settore."""
import inspect
import os
import unittest
from decimal import Decimal
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from pydantic import ValidationError  # noqa: E402

from app.api.v1 import supplier_price_links as links  # noqa: E402
from app.services import open_price_list_sector as sector  # noqa: E402


class SectorCategoriesTest(unittest.TestCase):
    def test_categories_enabled_by_the_office_win(self):
        # Alfa ed Eurocarta: abilitati a Materiali, vendono anche qualche Attrezzatura.
        self.assertEqual(sector.sector_categories([("Materiali", True)], {"Materiali", "Attrezzatura"}), {"materiali"})

    def test_without_settings_the_categories_of_its_products(self):
        self.assertEqual(sector.sector_categories([], {"Food", " "}), {"food"})

    def test_disabled_category_is_left_out(self):
        self.assertEqual(sector.sector_categories([("Food", False)], {"Food", "Bevande"}), {"bevande"})


class SectionsTest(unittest.TestCase):
    def test_only_enabled_sections(self):
        fruit = SimpleNamespace(subcategory="Frutta", sku_interno="A")
        meat = SimpleNamespace(subcategory="Carne", sku_interno="B")
        self.assertTrue(sector.in_sections(fruit, {"frutta"}, set()))
        self.assertFalse(sector.in_sections(meat, {"frutta"}, set()))

    def test_category_without_sections_takes_everything(self):
        self.assertTrue(sector.in_sections(SimpleNamespace(subcategory="Bicchieri", sku_interno="A"), None, set()))

    def test_product_without_section_stays_with_who_sells_it(self):
        product = SimpleNamespace(subcategory=None, sku_interno="A")
        self.assertTrue(sector.in_sections(product, {"frutta"}, {"A"}))
        self.assertFalse(sector.in_sections(product, {"frutta"}, set()))


class TopProductsTest(unittest.TestCase):
    def test_same_top_for_everyone_from_the_sector_list(self):
        spend = {"A": Decimal("10"), "B": Decimal("30"), "C": Decimal("0"), "D": Decimal("20")}
        self.assertEqual(links.top_products(["A", "B", "C", "D"], spend, limit=2), {"B", "D"})

    def test_never_bought_is_not_top(self):
        self.assertEqual(links.top_products(["C"], {"C": Decimal("0")}), set())


class PayloadTest(unittest.TestCase):
    def test_absent_only_is_a_valid_answer(self):
        self.assertEqual(links.PriceUpdates(assenti=["A"]).assenti, ["A"])

    def test_absent_and_price_together_is_refused(self):
        quote = {"sku_interno": "A", "nome": "Bicchiere 200", "unita_vendita": "CT", "contenuto_quantita": "100",
                 "contenuto_unita": "PZ", "prezzo": "5"}
        with self.assertRaises(ValidationError):
            links.PriceUpdates(assenti=["A"], quotazioni=[quote])

    def test_nothing_is_refused(self):
        with self.assertRaises(ValidationError):
            links.PriceUpdates()


class WiringTest(unittest.TestCase):
    def test_page_shows_the_sector_list(self):
        source = inspect.getsource(links.get_open_price_list)
        self.assertIn("sector_products(db, link.fornitore_id", source)
        self.assertIn('"da_quotare": quotes', source)

    def test_quote_becomes_a_linked_proposal_and_clears_absent(self):
        source = inspect.getsource(links._save_sector_answers)
        self.assertIn("sku_interno=quote.sku_interno", source)
        self.assertIn("await db.delete(absences.pop(quote.sku_interno))", source)


if __name__ == "__main__":
    unittest.main()
