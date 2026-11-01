import unittest

from app.services.normalized_price_workbook import parse_normalized_sheet_values


HEADERS = [
    "ID_PRODOTTO", "PRODOTTO", "SOTTOCATEGORIA", "ID_FORNITORE", "FORNITORE",
    "DICITURA_FORNITORE", "MARCA", "QUANTITA_CONFEZIONE", "UNITA_MISURA",
    "PREZZO_CONFEZIONE_EUR", "DATA_PREZZO", "NOTE",
]
SUPPLIER_HEADERS = [
    "ID_FORNITORE", "FORNITORE", "PARTITA_IVA", "FOOD", "BEVERAGE",
    "FRUTTA_E_VERDURA", "MATERIALI", "NOTE",
]


class NormalizedGoogleSheetTest(unittest.TestCase):
    def test_confirmed_package_is_normalized_and_source_price_preserved(self):
        values = {name: [HEADERS] for name in ("FOOD", "BEVERAGE", "FRUTTA E VERDURA", "MATERIALI")}
        values["FOOD"].append([
            "SG3-1234567890ABCDEF", "GELATO", "Varie", "F1", "Fornitore",
            "Gelato 2,8 kg", "Marca", 2.8, "KG", 14, "2026-10-27",
            "Conferma fornitore Price Sentinel",
        ])
        values["FORNITORI"] = [SUPPLIER_HEADERS, ["F1", "Fornitore", "", "SI", "", "", "", ""]]
        report = parse_normalized_sheet_values(values, "ABCDEFGHIJKLMNOPQRST")
        self.assertEqual(report["candidate_count"], 1)
        offer = report["candidates"][0]
        self.assertEqual(offer["quoted_value"], 14)
        self.assertEqual(offer["numeric_price"], "5.0000")
        self.assertEqual(offer["reference_unit"], "KG")
        values["FOOD"][1][-1] = ""
        unconfirmed = parse_normalized_sheet_values(values, "ABCDEFGHIJKLMNOPQRST")["candidates"][0]
        self.assertIn("package_price_not_single_unit", unconfirmed["reasons"])
        self.assertIsNone(unconfirmed["reference_unit"])


if __name__ == "__main__":
    unittest.main()
