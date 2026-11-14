"""Protezioni del catalogo: unità ammesse (modalità rigida), categoria obbligatoria,
controllo doppioni alla creazione di una voce dalla coda prodotti.

python -m unittest discover -s tests -p 'test_catalog_guards.py' -v   (da backend/, PYTHONPATH=.)
"""
import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Placeholder settings: these tests never open a database connection.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.api.v1 import product_identity as pi  # noqa: E402
from app.models.fatture import StatoMatching  # noqa: E402
from app.services.normalization import UnitNotAllowedError, canonical_unit, normalize_text  # noqa: E402


def catalog_product(product_id: int, name: str, **overrides):
    values = {
        "id": product_id, "sku_interno": f"SKU-{product_id}", "canonical_name": name,
        "normalized_name": normalize_text(name), "normalized_order_name": None,
        "volume_ml": None, "weight_g": None, "unit_count": 1, "brand": None, "category": None,
        "comparison_unit": "Pz", "container_type": None, "is_active": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class StrictCanonicalUnitTest(unittest.TestCase):
    def test_synonyms_found_in_production_are_mapped(self):
        cases = {
            "piece": "Pz", "PZ": "Pz", "NR": "Pz", "N.": "Pz", "BT": "Pz", "FL": "Pz",
            "Ct": "CT", "CT": "CT", "CS": "CT", "CF": "CT", "CNF": "CT", "conf": "CT", "Cassa": "CT",
            "KG": "Kg", "K.": "Kg", "kg": "Kg", "Lt": "Lt", "LT": "Lt", "L": "Lt", "litri": "Lt",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(canonical_unit(raw, strict=True), expected)

    def test_empty_means_unknown(self):
        self.assertIsNone(canonical_unit(None, strict=True))
        self.assertIsNone(canonical_unit("  ", strict=True))

    def test_unknown_unit_is_refused_not_guessed(self):
        for raw in ("COL", "FS", "TA", "scatolone"):
            with self.subTest(raw=raw):
                with self.assertRaises(UnitNotAllowedError):
                    canonical_unit(raw, strict=True)
                # La modalità tollerante (import) la lascia com'è.
                self.assertEqual(canonical_unit(raw), raw)


class ProductSchemaUnitTest(unittest.TestCase):
    def test_create_and_update_store_canonical_unit(self):
        self.assertEqual(pi.ProductCreate(canonical_name="X", comparison_unit="Ct").comparison_unit, "CT")
        self.assertEqual(pi.ProductUpdate(comparison_unit="piece").comparison_unit, "Pz")
        self.assertIsNone(pi.ProductUpdate(comparison_unit=None).comparison_unit)

    def test_create_and_update_refuse_unknown_unit(self):
        with self.assertRaises(ValidationError):
            pi.ProductCreate(canonical_name="X", comparison_unit="COL")
        with self.assertRaises(ValidationError):
            pi.ProductUpdate(comparison_unit="box grande")

    def test_response_keeps_legacy_units(self):
        # Le voci già salvate con unità vecchie ("CP") si devono ancora poter leggere.
        self.assertEqual(pi.ProductBase(canonical_name="X", comparison_unit="CP").comparison_unit, "CP")

    def test_work_queue_product_defaults_to_pz_and_maps_listino_unit(self):
        product = pi.WorkQueueResolutionProduct(canonical_name="X")
        self.assertEqual(product.comparison_unit, "Pz")
        self.assertEqual(pi.WorkQueueResolutionProduct(canonical_name="X", comparison_unit="piece").comparison_unit, "Pz")
        self.assertEqual(pi.WorkQueueResolutionProduct(canonical_name="X", unita_misura_listino="K.").unita_misura_listino, "Kg")
        with self.assertRaises(ValidationError):
            pi.WorkQueueResolutionProduct(canonical_name="X", comparison_unit="COL")
        # Unità di fattura sconosciuta: non blocca una risoluzione massiva e resta com'è.
        request = pi.WorkQueueResolutionRequest(invoice_line_ids=[1], action="ignore", unita_misura_listino="COL")
        self.assertEqual(request.unita_misura_listino, "COL")
        self.assertFalse(request.allow_similar)


class SimilarProductsTest(unittest.TestCase):
    def setUp(self):
        self.products = [
            catalog_product(362, "MARTINI BITTER LT 1"),
            catalog_product(309, "GIN BEEFEATER RED 70 CL"),
            catalog_product(600, "Svelto piatti 10 litri"),
        ]
        self.index = pi._build_live_catalog_index(self.products)

    def test_same_product_written_differently_is_reported(self):
        similar = pi._similar_catalog_products(["BITTER MARTINI 1 LT"], self.index)
        self.assertEqual([item["product_id"] for item in similar], [362])

    def test_different_format_or_unrelated_product_is_not_reported(self):
        self.assertEqual(pi._similar_catalog_products(["GIN BEEFEATER RED 1 LT"], self.index), [])
        self.assertEqual(pi._similar_catalog_products(["FARINA 00 DIVELLA 1 KG", ""], self.index), [])

    def test_product_created_in_the_same_batch_is_seen(self):
        new = catalog_product(9001, "PANNA DEBIC 1 LT")
        self.assertEqual(pi._similar_catalog_products(["PANNA DEBIC LT 1"], self.index), [])
        pi._extend_catalog_index(self.index, new)
        self.assertEqual([i["product_id"] for i in pi._similar_catalog_products(["PANNA DEBIC LT 1"], self.index)], [9001])


def _work_queue_db(line, invoice, category_rows):
    db = MagicMock()
    rows = MagicMock()
    rows.all.return_value = [(line, invoice)]
    db.execute = AsyncMock(return_value=rows)
    db.scalar = AsyncMock(side_effect=category_rows)
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


class CreateCanonicalGuardTest(unittest.TestCase):
    def setUp(self):
        self.line = SimpleNamespace(
            id=10, stato_matching=StatoMatching.in_parking, codice_fornitore_raw="BITTE02",
            descrizione_fornitore_raw="BITTER MARTINI 1 LT",
        )
        self.invoice = SimpleNamespace(fornitore_id=22)
        self.index = pi._build_live_catalog_index([catalog_product(362, "MARTINI BITTER LT 1")])

    def request(self, **overrides):
        values = {
            "invoice_line_ids": [10], "action": "create_canonical",
            "canonical_data": pi.WorkQueueResolutionProduct(canonical_name="BITTER MARTINI 1 LT", category="Beverage"),
        }
        values.update(overrides)
        return pi.WorkQueueResolutionRequest(**values)

    def test_similar_product_stops_creation_before_any_write(self):
        db = _work_queue_db(self.line, self.invoice, ["Beverage"])
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(pi._resolve_single_work_item(db, self.request(), catalog_index=self.index))
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.detail["code"], "similar_products")
        self.assertEqual(caught.exception.detail["similar_products"][0]["product_id"], 362)
        db.add.assert_not_called()

    def test_missing_category_is_refused(self):
        db = _work_queue_db(self.line, self.invoice, [])
        data = self.request(canonical_data=pi.WorkQueueResolutionProduct(canonical_name="NUOVO PRODOTTO"))
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(pi._resolve_single_work_item(db, data, catalog_index=self.index))
        self.assertEqual(caught.exception.status_code, 422)
        db.add.assert_not_called()

    def test_unknown_category_is_refused(self):
        db = _work_queue_db(self.line, self.invoice, [None, None])
        data = self.request(canonical_data=pi.WorkQueueResolutionProduct(canonical_name="X", category="Bevande varie"))
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(pi._resolve_single_work_item(db, data, catalog_index=self.index))
        self.assertEqual(caught.exception.status_code, 422)
        db.add.assert_not_called()

    def test_legacy_materiali_di_consumo_label_is_mapped(self):
        db = MagicMock()
        db.scalar = AsyncMock(return_value="Materiali")
        self.assertEqual(asyncio.run(pi._known_category(db, "Materiali di consumo")), "Materiali")


if __name__ == "__main__":
    unittest.main()
