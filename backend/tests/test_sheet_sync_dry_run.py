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

    def test_five_sector_sources(self):
        report = self.preview()
        self.assertEqual(len(SOURCES), 5)
        self.assertEqual(len(report["sector_summary"]), 5)
        self.assertEqual(report["candidate_count"], 30)
        self.assertEqual(report["missing_sources"], [])
        self.assertEqual(
            sum(section["products"] for section in report["sector_summary"]), 9
        )
        self.assertTrue(report["no_contract_writes"])
        self.assertFalse(report["rules"]["auto_commit_enabled"])
        self.assertTrue(all(c["status"] != "auto_eligible" for c in report["candidates"]))

    def test_sheet_exclusion_keeps_original_quote_and_note(self):
        report = self.preview()
        q = next(c for c in report["candidates"] if
                 c["source_sheet"] == "FOOD" and c["source_cell"] == "F3")
        self.assertEqual(q["supplier"], "ORIZZONTI")
        self.assertEqual(q["numeric_price"], "5.9")
        self.assertEqual(q["status"], "blocked")
        self.assertIn("sheet_exclusion", q["reasons"])
        self.assertIn("5,90", q["cell_note"])
        # A valid competitor on the same row must remain available for review.
        other = next(c for c in report["candidates"] if
                     c["source_sheet"] == "FOOD" and c["source_cell"] == "E3")
        self.assertEqual(other["status"], "needs_approval")

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
        candidates = [c for c in self.preview()["candidates"] if c["sector"] == "giocattoli"]
        self.assertEqual(len(candidates), 2)
        self.assertTrue(all(
            "supplier_identity_and_net_price_need_verification" in c["reasons"]
            for c in candidates
        ))
        self.assertTrue(all(c["status"] == "needs_approval" for c in candidates))

    def test_mismatched_supplier_header_fails_closed(self):
        data = copy.deepcopy(self.snapshot)
        data["values"]["FOOD"][0][2] = "UNKNOWN"
        report = self.preview(data)
        self.assertIn("FOOD", report["missing_sources"])
        self.assertFalse(any(c["source_sheet"] == "FOOD" for c in report["candidates"]))

    def test_missing_exclusion_control_fails_closed(self):
        data = copy.deepcopy(self.snapshot)
        del data["values"]["CONTROLLO_ESCLUSIONI"]
        report = self.preview(data)
        self.assertIn("CONTROLLO_ESCLUSIONI", report["missing_sources"])
        self.assertFalse(any(c["source_sheet"] == "FOOD" for c in report["candidates"]))

    def test_name_duplicates_alert_without_merging(self):
        data = copy.deepcopy(self.snapshot)
        data["values"]["FOOD"].append(list(data["values"]["FOOD"][1]))
        report = self.preview(data)
        self.assertTrue(any(w["code"] == "duplicate_product_name" for w in report["warnings"]))

    def test_observation_hash_ignores_row_position(self):
        a = self.preview()
        data = copy.deepcopy(self.snapshot)
        data["values"]["FOOD"].insert(1, ["", "", "", "", "", "", "", "", "", ""])
        data["values"]["CONTROLLO_ESCLUSIONI"][1][0] += 1
        b = self.preview(data)
        h1 = next(c for c in a["candidates"] if c["source_sheet"] == "FOOD"
                  and c["source_cell"] == "F3")["observation_hash"]
        h2 = next(c for c in b["candidates"] if c["source_sheet"] == "FOOD"
                  and c["source_cell"] == "F4")["observation_hash"]
        self.assertEqual(h1, h2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
