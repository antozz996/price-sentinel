"""Offline tests for the Google Sheets multi-sector reader (no Google credentials or DB)."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from app.services.sheet_sync_dry_run import SOURCES, stage_snapshot

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sheets_sync_synthetic.json"


class SheetSyncDryRunTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def preview(self, snapshot=None):
        snapshot = snapshot or self.snapshot
        return stage_snapshot(
            snapshot["values"],
            spreadsheet_id=snapshot.get("spreadsheet_id", ""),
            notes=snapshot.get("notes", {}),
        )

    def test_seven_sheet_sources(self):
        report = self.preview()
        self.assertEqual(len(SOURCES), 7)
        self.assertNotIn("FOOD", {source.title for source in SOURCES})
        self.assertEqual(len(report["sector_summary"]), 7)
        self.assertEqual(report["candidate_count"], 32)
        self.assertEqual(report["missing_sources"], [])
        self.assertEqual(
            sum(section["products"] for section in report["sector_summary"]), 11
        )
        self.assertTrue(report["no_contract_writes"])
        self.assertFalse(report["rules"]["auto_commit_enabled"])
        self.assertEqual(report["rules"]["price_semantics"], "negotiated_agreement")
        self.assertTrue(all(c["status"] != "auto_eligible" for c in report["candidates"]))
        fruit = next(c for c in report["candidates"] if c["source_sheet"] == "FRUTTA E VERDURA")
        self.assertEqual(fruit["sector"], "Food")
        self.assertEqual(fruit["subcategory"], "Frutta")
        carne = next(c for c in report["candidates"] if c["source_sheet"] == "Carne")
        self.assertEqual(carne["subcategory"], "Carne")
        self.assertEqual(carne["source_original_row"], 20)
        pesce = next(c for c in report["candidates"] if c["source_sheet"] == "Pesce")
        self.assertEqual(pesce["subcategory"], "Pesce")
        varie = next(c for c in report["candidates"] if c["source_sheet"] == "Varie")
        self.assertIsNone(varie["subcategory"])

    def test_sheet_exclusion_keeps_original_quote_and_note(self):
        report = self.preview()
        q = next(c for c in report["candidates"] if
                 c["source_sheet"] == "Varie" and c["source_cell"] == "F3")
        self.assertEqual(q["supplier"], "ORIZZONTI")
        self.assertEqual(q["source_original_row"], 3)
        self.assertEqual(q["numeric_price"], "5.9")
        self.assertEqual(q["status"], "blocked")
        self.assertIn("sheet_exclusion", q["reasons"])
        self.assertIn("5,90", q["cell_note"])
        # A valid competitor on the same row must remain available for review.
        other = next(c for c in report["candidates"] if
                     c["source_sheet"] == "Varie" and c["source_cell"] == "E3")
        self.assertEqual(other["status"], "needs_mapping")
        self.assertEqual(other["price_role"], "negotiated_agreement")
        self.assertTrue(other["requires_product_mapping"])
        self.assertIn("canonical_id_not_mapped", other["reasons"])
        self.assertNotIn("agreement_approval_required", other["reasons"])

    def test_unit_conflict_zero_and_malformed_price(self):
        candidates = self.preview()["candidates"]
        unit = next(c for c in candidates if
                    c["source_sheet"] == "FRUTTA E VERDURA" and c["source_cell"] == "E2")
        self.assertIn("unit_mismatch_needs_conversion", unit["reasons"])
        self.assertEqual(unit["status"], "blocked")
        zero = next(c for c in candidates if
                    c["source_sheet"] == "FRUTTA E VERDURA" and c["source_cell"] == "E3")
        self.assertIn("zero_or_negative", zero["reasons"])
        self.assertEqual(zero["status"], "blocked")
        malformed = next(c for c in candidates if
                         c["source_sheet"] == "COMPARAZIONE MATERIALI" and c["source_cell"] == "D2")
        self.assertIn("textual_price", malformed["reasons"])
        self.assertEqual(malformed["status"], "blocked")
        self.assertFalse(any(c["source_sheet"] == "BEVERAGE" and c["source_cell"] == "J2"
                             for c in candidates))  # derived error columns ignored

    def test_beverage_precision_and_derived_lookup(self):
        candidates = self.preview()["candidates"]
        price = next(c for c in candidates if
                     c["source_sheet"] == "BEVERAGE" and c["source_cell"] == "E3")
        self.assertIn("precision_review", price["reasons"])
        lookup = next(c for c in candidates if
                      c["source_sheet"] == "BEVERAGE" and c["source_cell"] == "D2")
        self.assertIn("derived_supplier_lookup", lookup["reasons"])

    def test_giocattoli_only_review(self):
        candidates = [c for c in self.preview()["candidates"] if c["sector"] == "Giocattoli"]
        self.assertEqual(len(candidates), 2)
        self.assertTrue(all(
            "supplier_identity_and_net_price_need_verification" in c["reasons"]
            for c in candidates
        ))
        self.assertTrue(all(c["status"] == "needs_mapping" for c in candidates))

    def test_mismatched_supplier_header_fails_closed(self):
        data = copy.deepcopy(self.snapshot)
        data["values"]["Carne"][0][2] = "UNKNOWN"
        report = self.preview(data)
        self.assertIn("Carne", report["missing_sources"])
        self.assertFalse(any(c["source_sheet"] == "Carne" for c in report["candidates"]))

    def test_missing_food_origin_header_fails_closed_for_that_tab(self):
        data = copy.deepcopy(self.snapshot)
        data["values"]["Carne"][0][10] = "RIFERIMENTO ERRATO"
        report = self.preview(data)
        self.assertIn("Carne", report["missing_sources"])
        self.assertFalse(any(c["source_sheet"] == "Carne" for c in report["candidates"]))

    def test_food_tabs_accept_di_palo_description_column_and_import_price(self):
        data = copy.deepcopy(self.snapshot)
        for tab in ("Carne", "Pesce", "Varie"):
            for row in data["values"][tab]:
                row.insert(8, "DESCRIZIONE DI PALO" if row is data["values"][tab][0] else None)
        # The description column is informational; the negotiated amount remains in H.
        data["values"]["Carne"][1][7] = 8.19
        data["values"]["Carne"][1][8] = "POLLO FRESCO DI PALO"
        report = self.preview(data)
        self.assertNotIn("Carne", report["missing_sources"])
        quote = next(c for c in report["candidates"] if
                     c["source_sheet"] == "Carne" and c["source_cell"] == "H2")
        self.assertEqual(quote["supplier"], "DI PALO")
        self.assertEqual(quote["numeric_price"], "8.19")
        self.assertEqual(quote["source_original_row"], 20)

    def test_missing_exclusion_control_fails_closed(self):
        data = copy.deepcopy(self.snapshot)
        del data["values"]["CONTROLLO_ESCLUSIONI"]
        report = self.preview(data)
        self.assertIn("CONTROLLO_ESCLUSIONI", report["missing_sources"])
        food_tabs = {"Carne", "Pesce", "Varie"}
        self.assertFalse(any(c["source_sheet"] in food_tabs for c in report["candidates"]))

    def test_corrupt_exclusion_register_fails_closed(self):
        data = copy.deepcopy(self.snapshot)
        data["values"]["CONTROLLO_ESCLUSIONI"][0][5] = "OTHER"
        report = self.preview(data)
        self.assertIn("CONTROLLO_ESCLUSIONI", report["missing_sources"])
        food_tabs = {"Carne", "Pesce", "Varie"}
        self.assertFalse(any(c["source_sheet"] in food_tabs for c in report["candidates"]))

    def test_name_duplicates_alert_without_merging(self):
        data = copy.deepcopy(self.snapshot)
        data["values"]["Varie"].append(list(data["values"]["Varie"][1]))
        report = self.preview(data)
        self.assertTrue(any(w["code"] == "duplicate_product_name" for w in report["warnings"]))

    def test_observation_hash_ignores_row_position(self):
        a = self.preview()
        data = copy.deepcopy(self.snapshot)
        data["values"]["Varie"].insert(1, ["", "", "", "", "", "", "", "", "", "", ""])
        data["notes"]["Varie"]["F4"] = data["notes"]["Varie"].pop("F3")
        b = self.preview(data)
        h1 = next(c for c in a["candidates"] if c["source_sheet"] == "Varie"
                  and c["source_cell"] == "F3")["observation_hash"]
        h2 = next(c for c in b["candidates"] if c["source_sheet"] == "Varie"
                  and c["source_cell"] == "F4")["observation_hash"]
        self.assertEqual(h1, h2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
