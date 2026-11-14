"""PR-E correzioni minori: scelta fornitore sul prezzo normalizzato, chiusura dei
listini al giorno prima, unità confrontate per famiglia, anomalie lavorate
conservate, fornitori archiviati esclusi dal foglio prezzi.

PYTHONPATH=. python -m unittest discover -s tests -p 'test_correzioni_minori.py' -v   (da backend/)
"""
import asyncio
import os
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Placeholder settings: these tests never open a database connection.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from app.services.matching import pack_mismatch_blocks  # noqa: E402
from app.services.normalization import unit_family  # noqa: E402
from app.services.order_resolver import convert_requested_quantity  # noqa: E402
from app.services.purchase_recommendation import (  # noqa: E402
    cheapest_comparable_listino,
    comparable_listino_price,
    rank_offers_keeping_incomparable,
)
from app.services.variant_price_import import (  # noqa: E402
    cut_offer_rows_at,
    cut_other_supplier_rows_at,
    previous_price_end,
)


def product(comparison_unit="Pz", unit_count=1, volume_ml=None, weight_g=None):
    return SimpleNamespace(comparison_unit=comparison_unit, unit_count=unit_count,
                           volume_ml=volume_ml, weight_g=weight_g)


def listino(row_id, supplier_id, price, unit, alias_id=None):
    return SimpleNamespace(id=row_id, fornitore_id=supplier_id, prezzo_pattuito=Decimal(price),
                           unita_misura=unit, supplier_product_alias_id=alias_id)


def price_row(start, end=None):
    return SimpleNamespace(data_inizio_validita=start, data_scadenza=end)


# 1. Scelta del fornitore sul prezzo nell'unità di confronto
class CheapestComparableListinoTest(unittest.TestCase):
    def test_raw_price_without_unit_does_not_win(self):
        # DI PALO lievito 0,22 senza unità contro DAC 5,27 al pezzo: vince DAC.
        rows = [listino(1, 10, "0.22", None), listino(2, 20, "5.27", "PZ")]
        self.assertEqual(cheapest_comparable_listino(rows, product("Pz")).fornitore_id, 20)

    def test_box_price_is_compared_per_piece(self):
        # 24,00 al cartone da 30 pezzi = 0,80 al pezzo: batte 1,00 al pezzo.
        rows = [listino(1, 10, "1.00", "PZ"), listino(2, 20, "24.00", "CT", alias_id=7)]
        aliases = {7: SimpleNamespace(pack_qty=30, raw_description="", volume_ml=None, weight_g=None)}
        best = cheapest_comparable_listino(rows, product("Pz"), aliases)
        self.assertEqual(best.fornitore_id, 20)
        self.assertEqual(comparable_listino_price(rows[1], product("Pz"), aliases[7]), Decimal("0.8"))

    def test_unreliable_prices_are_excluded(self):
        # Prezzo al kg su una voce a pezzi: non confrontabile, nessuna scelta automatica.
        rows = [listino(1, 10, "0.50", "KG"), listino(2, 20, "0.10", "")]
        self.assertIsNone(cheapest_comparable_listino(rows, product("Pz")))
        self.assertIsNone(comparable_listino_price(rows[0], product("Pz")))

    def test_matrix_keeps_incomparable_offer_out_of_ranking(self):
        offers = [
            {"supplier_id": 10, "unit_price_normalized": None, "price": "0.2200", "source_type": "contratto"},
            {"supplier_id": 20, "unit_price_normalized": "5.2700", "price": "5.2700", "source_type": "contratto"},
        ]
        result = rank_offers_keeping_incomparable(offers)
        self.assertEqual(result["absolute_cheapest"]["supplier_id"], 20)
        self.assertEqual(result["recommended_offer"]["supplier_id"], 20)
        manual = next(o for o in result["offers"] if o["supplier_id"] == 10)
        self.assertFalse(manual["is_recommended"])
        self.assertFalse(manual["is_absolute_cheapest"])
        self.assertTrue(manual["eligible"])


# 2. Il listino sostituito finisce il giorno prima
class PreviousPriceEndTest(unittest.TestCase):
    def test_old_price_ends_the_day_before(self):
        self.assertEqual(previous_price_end(date(2026, 1, 1), date(2026, 11, 14)), date(2026, 11, 13))

    def test_never_an_inverted_interval(self):
        self.assertEqual(previous_price_end(date(2026, 11, 14), date(2026, 11, 14)), date(2026, 11, 14))
        self.assertEqual(previous_price_end(date(2026, 11, 20), date(2026, 11, 14)), date(2026, 11, 20))

    def test_supplier_list_import_closes_the_day_before(self):
        from app.services.supplier_list_import import save_append_only_price

        current = SimpleNamespace(prezzo_pattuito=Decimal("2.00"), unita_misura="Pz",
                                  data_inizio_validita=date(2026, 1, 1), data_scadenza=None)
        result = MagicMock()
        result.scalars.return_value.all.return_value = [current]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)
        outcome = asyncio.run(save_append_only_price(
            db, 1, "SKU-1", "Prodotto", Decimal("2.50"), "Pz", date(2026, 11, 14), supplier_product_alias_id=5,
        ))
        self.assertEqual(outcome, "updated")
        self.assertEqual(current.data_scadenza, date(2026, 11, 13))
        new_row = db.add.call_args_list[-1].args[0]
        self.assertEqual(new_row.data_inizio_validita, date(2026, 11, 14))


# 3. Il foglio prezzi chiude anche i listini legati al collegamento della fattura
class CutOtherSupplierRowsTest(unittest.TestCase):
    def test_open_and_overlapping_rows_end_the_day_before(self):
        start = date(2026, 11, 14)
        open_row = price_row(date(2026, 1, 1))
        overlapping = price_row(date(2026, 10, 1), date(2026, 12, 31))
        cut_other_supplier_rows_at([open_row, overlapping], start)
        self.assertEqual(open_row.data_scadenza, date(2026, 11, 13))
        self.assertEqual(overlapping.data_scadenza, date(2026, 11, 13))

    def test_expired_or_later_rows_are_untouched(self):
        start = date(2026, 11, 14)
        expired = price_row(date(2026, 1, 1), date(2026, 6, 30))
        later = price_row(date(2026, 11, 14))
        cut_other_supplier_rows_at([expired, later], start)
        self.assertEqual(expired.data_scadenza, date(2026, 6, 30))
        self.assertIsNone(later.data_scadenza)

    def test_offer_rows_rule_is_unchanged(self):
        # cut_offer_rows_at (rinnovo moduli) continua a ignorare le righe senza scadenza.
        open_row = price_row(date(2026, 1, 1))
        cut_offer_rows_at([open_row], date(2026, 11, 14))
        self.assertIsNone(open_row.data_scadenza)


# 4. Unità confrontate per famiglia, non come testo
class UnitFamilyTest(unittest.TestCase):
    def test_family(self):
        for raw, expected in {"Pz": "Pz", "piece": "Pz", "BT": "Pz", "bottle": "Pz", "CT": "CT",
                              "box": "CT", "conf": "CT", "Kg": "Kg", "kg": "Kg", "Lt": "Lt",
                              "liter": "Lt", "package": None, "": None, None: None}.items():
            with self.subTest(raw=raw):
                self.assertEqual(unit_family(raw), expected)

    def test_quantity_conversion_with_catalogue_units(self):
        self.assertEqual(convert_requested_quantity(Decimal("2"), "CT", "Pz", 6, 0, 0), Decimal("12"))
        self.assertEqual(convert_requested_quantity(Decimal("2"), "box", "piece", 6, 0, 0), Decimal("12"))
        self.assertEqual(convert_requested_quantity(Decimal("12"), "Pz", "CT", 6, 0, 0), Decimal("2"))
        self.assertEqual(convert_requested_quantity(Decimal("4"), "Pz", "Lt", 1, 750, 0), Decimal("3"))
        self.assertEqual(convert_requested_quantity(Decimal("4"), "Pz", "Kg", 1, 0, 500), Decimal("2"))
        # Stessa famiglia o unità sconosciuta: nessuna conversione.
        self.assertEqual(convert_requested_quantity(Decimal("3"), "Pz", "Pz", 6, 0, 0), Decimal("3"))
        self.assertEqual(convert_requested_quantity(Decimal("3"), "package", "Pz", 6, 0, 0), Decimal("3"))
        self.assertEqual(convert_requested_quantity(Decimal("3"), "CT", None, 6, 0, 0), Decimal("3"))

    def test_pack_mismatch_blocks_box_products(self):
        self.assertTrue(pack_mismatch_blocks("CT", 12, 6))
        self.assertTrue(pack_mismatch_blocks("box", 12, 6))
        self.assertFalse(pack_mismatch_blocks("CT", 6, 6))
        self.assertFalse(pack_mismatch_blocks("Pz", 12, 6))
        # unit_count 1 è il valore predefinito, non una confezione: non blocca.
        self.assertFalse(pack_mismatch_blocks("CT", 12, 1))
        self.assertFalse(pack_mismatch_blocks("CT", None, 6))


# 5. La coda prodotti archivia solo le anomalie non lavorate
class QueueAnomalyRefreshTest(unittest.TestCase):
    def run_refresh(self, worked_id, delta, delta_total, in_scope=True):
        from app.api.v1 import product_identity as pi

        db = MagicMock()
        db.scalar = AsyncMock(return_value=worked_id)
        archive = AsyncMock(return_value=0)
        line = SimpleNamespace(id=10)
        invoice = SimpleNamespace(xml_raw_id=3)
        listino_row = SimpleNamespace(prezzo_pattuito=Decimal("5.00"))
        with patch("app.services.anomaly_policy.archive_and_remove_anomalies", archive), \
                patch("app.services.anomaly_policy.invoice_in_check_scope", AsyncMock(return_value=in_scope)):
            asyncio.run(pi._refresh_queue_line_anomaly(
                db, line, invoice, listino_row, Decimal("6.00"), Decimal(delta), Decimal(delta_total),
            ))
        return db, archive

    def test_only_unworked_states_are_archived(self):
        _, archive = self.run_refresh(None, "1.00", "10.00")
        conditions = " ".join(str(c) for c in archive.call_args.args[1:])
        self.assertIn("stato_validazione", conditions)
        self.assertEqual(archive.call_args.kwargs["reason"], "risoluzione_coda")

    def test_new_anomaly_when_nothing_worked_remains(self):
        db, _ = self.run_refresh(None, "1.00", "10.00")
        db.add.assert_called_once()
        self.assertEqual(db.add.call_args.args[0].riga_fattura_id, 10)

    def test_worked_anomaly_is_kept_and_not_duplicated(self):
        db, _ = self.run_refresh(99, "1.00", "10.00")
        db.add.assert_not_called()

    def test_no_anomaly_under_threshold(self):
        db, _ = self.run_refresh(None, "0.00", "0.00")
        db.add.assert_not_called()


# 6. Il foglio prezzi non riconosce i fornitori archiviati
class ArchivedSupplierHeaderTest(unittest.TestCase):
    def build(self, suppliers, supplier_mapping):
        from app.services import smart_price_sheet as sps

        def scalars_result(rows):
            result = MagicMock()
            result.all.return_value = rows
            return result

        db = MagicMock()
        db.scalars = AsyncMock(side_effect=[scalars_result(suppliers)] + [scalars_result([]) for _ in range(10)])
        db.scalar = AsyncMock(return_value=None)
        db.execute = AsyncMock(return_value=MagicMock())
        db.flush = AsyncMock()
        scope = MagicMock()
        scope.eligible_supplier_ids.return_value = set()
        with patch.object(sps, "load_supplier_catalog_scope", AsyncMock(return_value=scope)):
            preview = asyncio.run(sps.build_price_preview(
                db, text_value="Prodotto;KITO\nFarina 00;1,50", supplier_mapping=supplier_mapping,
                product_mapping={}, effective_date=date(2026, 11, 14), default_uom="Pz",
                create_missing_products=False, location_id=None, actor_id=1,
            ))
        return {row["header"]: row for row in preview.preview_payload["supplier_mapping"]}

    def supplier(self, supplier_id, name, archived):
        return SimpleNamespace(id=supplier_id, nome_azienda=name, partita_iva=f"TEMP{supplier_id}",
                               archived_at=datetime(2026, 11, 1, tzinfo=timezone.utc) if archived else None,
                               attivo_whitelist=True)

    def test_archived_supplier_is_not_matched_by_name(self):
        mapping = self.build([self.supplier(7, "KITO", True), self.supplier(30, "KITO SRL", False)], {})
        self.assertEqual(mapping["KITO"]["supplier_id"], 30)

    def test_only_archived_match_stays_unresolved(self):
        mapping = self.build([self.supplier(7, "KITO", True)], {})
        self.assertIsNone(mapping["KITO"]["supplier_id"])

    def test_explicit_archived_supplier_is_refused(self):
        mapping = self.build([self.supplier(7, "KITO", True)], {"KITO": 7})
        self.assertEqual(mapping["KITO"]["method"], "archived")
        self.assertIsNone(mapping["KITO"]["supplier_id"])


if __name__ == "__main__":
    unittest.main()
