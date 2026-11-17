"""Origine del prezzo in listino_master e scelta del prezzo valido senza fornitore.

Nessun database: regole Python e controllo statico dei punti in cui nasce un prezzo.
"""
import inspect
import os
import re
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from app.models import listino as listino_model  # noqa: E402
from app.models.listino import ListinoMaster  # noqa: E402
from app.services import variant_price_import as vpi  # noqa: E402

APP_DIR = Path(__file__).resolve().parents[1] / "app"
# File che creano ListinoMaster senza essere un percorso reale di produzione:
# dati demo, script di prova, e un ramo morto di ordini.py che usa campi inesistenti.
NOT_PRODUCTION = {
    "models/listino.py", "seed/product_identity_seed.py", "services/seed.py",
    "services/test_api_resolution.py", "services/test_matching_v2.py", "api/v1/ordini.py",
}


def row(fornitore, sku="GIN", start=date(2026, 11, 1), end=None):
    return SimpleNamespace(fornitore_id=fornitore, sku_interno=sku, data_inizio_validita=start, data_scadenza=end)


class SoleActivePriceTest(unittest.TestCase):
    def test_one_price_is_returned(self):
        only = row(1)
        self.assertIs(vpi.sole_active_price([only]), only)

    def test_two_suppliers_means_no_choice(self):
        # Prima si prendeva il primo e si chiudeva il prezzo di un altro fornitore.
        self.assertIsNone(vpi.sole_active_price([row(1), row(2)]))

    def test_two_offers_same_supplier_means_no_choice(self):
        self.assertIsNone(vpi.sole_active_price([row(1), row(1)]))

    def test_no_price(self):
        self.assertIsNone(vpi.sole_active_price([]))


class OriginColumnTest(unittest.TestCase):
    def test_column_exists_and_is_optional(self):
        column = ListinoMaster.__table__.c.origine
        self.assertTrue(column.nullable)
        self.assertEqual(column.type.length, 30)

    def test_origins_fit_the_column(self):
        self.assertEqual(len(set(listino_model.ORIGINI_PREZZO)), len(listino_model.ORIGINI_PREZZO))
        self.assertTrue(all(len(value) <= 30 for value in listino_model.ORIGINI_PREZZO))

    def test_variant_commit_defaults_to_price_sheet(self):
        default = inspect.signature(vpi.commit_variant_preview).parameters["origine"].default
        self.assertEqual(default, listino_model.ORIGINE_FOGLIO_PREZZI)

    def test_every_production_write_sets_origin(self):
        missing = []
        for path in APP_DIR.rglob("*.py"):
            rel = path.relative_to(APP_DIR).as_posix()
            if rel in NOT_PRODUCTION:
                continue
            source = path.read_text(encoding="utf-8")
            for match in re.finditer(r"ListinoMaster\(", source):
                depth, end = 0, match.end() - 1
                for end in range(match.end() - 1, len(source)):
                    depth += {"(": 1, ")": -1}.get(source[end], 0)
                    if depth == 0:
                        break
                if "origine=" not in source[match.start():end]:
                    missing.append(f"{rel}:{source.count(chr(10), 0, match.start()) + 1}")
        self.assertEqual(missing, [], "ListinoMaster creato senza origine")


if __name__ == "__main__":
    unittest.main()
