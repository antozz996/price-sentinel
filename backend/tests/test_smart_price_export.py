import unittest
from io import BytesIO

from openpyxl import load_workbook

from app.services.smart_price_export import BASE_COLUMNS, build_matrix_workbook

SUPPLIERS = [{"id": 1, "name": "NAVAS", "vat": "1"}, {"id": 2, "name": "SIRO", "vat": "2"},
             {"id": 3, "name": "SENZA OFFERTE", "vat": "3"}, {"id": 1, "name": "NAVAS", "vat": "1"}]
ROWS = [
    {"canonical_name": "RED BULL 0,25 X24 LATT", "sku_interno": "SKU1", "category": "Beverage", "comparison_unit": "Pz",
     "acquisti": 12, "quantita": "40", "spesa": "786.80", "ultimo_acquisto": "2026-11-02",
     "recommended_supplier_id": 2, "absolute_cheapest_supplier_id": 2,
     "offers": {"1": {"unit_price_normalized": "19.6700", "price": "19.67", "uom": "CT"},
                "2": {"unit_price_normalized": "19.5082", "price": "19.5082", "uom": "CT"}}},
    {"canonical_name": "MOET ICE", "sku_interno": "SKU2", "category": "Beverage", "comparison_unit": "Pz",
     "offers": {"1": {"unit_price_normalized": None, "price": "36.86", "uom": "XX"}}},
]


class MatrixWorkbookTest(unittest.TestCase):
    def setUp(self):
        self.ws = load_workbook(BytesIO(build_matrix_workbook(ROWS, SUPPLIERS, "Beverage"))).active

    def test_only_suppliers_with_offers_once(self):
        header = [c.value for c in self.ws[1]]
        self.assertEqual(header[len(BASE_COLUMNS):], ["NAVAS", "SIRO"])

    def test_prices_and_recommendation(self):
        row = [c.value for c in self.ws[2]]
        self.assertEqual(row[0], "RED BULL 0,25 X24 LATT")
        self.assertEqual(row[10], "SIRO")
        self.assertAlmostEqual(row[len(BASE_COLUMNS)], 19.67)
        self.assertAlmostEqual(row[len(BASE_COLUMNS) + 1], 19.5082)
        self.assertEqual(self.ws.cell(2, len(BASE_COLUMNS) + 2).fill.fgColor.rgb[-6:], "C6EFCE")

    def test_not_comparable_price_kept_as_text(self):
        self.assertEqual(self.ws.cell(3, len(BASE_COLUMNS) + 1).value, "36.86 XX")
        self.assertIsNone(self.ws.cell(3, len(BASE_COLUMNS) + 2).value)


if __name__ == "__main__":
    unittest.main()
