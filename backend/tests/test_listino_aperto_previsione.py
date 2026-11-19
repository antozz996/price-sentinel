"""Listino sempre aperto: chi sarà il fornitore più conveniente quando un aumento entra."""
import inspect
import os
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from app.api.v1 import supplier_price_links as links  # noqa: E402
from app.models import supplier_price_link as spl  # noqa: E402
from app.services import open_price_list_forecast as forecast  # noqa: E402

DEC1 = date(2026, 12, 1)


def _row(id, fornitore, price, alias=None):
    return SimpleNamespace(id=id, fornitore_id=fornitore, sku_interno="ZUC", supplier_product_alias_id=alias,
                           unita_misura="kg", prezzo_pattuito=Decimal(price))


def _change(fornitore, tipo, price=None, stato=spl.STATO_PROGRAMMATO, day=DEC1, alias=None):
    return SimpleNamespace(fornitore_id=fornitore, chiave_offerta=spl.offer_key("ZUC", alias), tipo=tipo,
                           prezzo_nuovo=None if price is None else Decimal(price), stato=stato, decorrenza=day)


class ApplyScheduledTest(unittest.TestCase):
    def test_increase_counts_from_its_date(self):
        rows = [_row(1, 10, "1.50"), _row(2, 20, "1.60")]
        changes = [_change(10, spl.TIPO_AUMENTO, "1.80")]
        self.assertEqual([r.prezzo_pattuito for r in forecast.apply_scheduled(rows, changes, date(2026, 11, 30))],
                         [Decimal("1.50"), Decimal("1.60")])
        self.assertEqual([r.prezzo_pattuito for r in forecast.apply_scheduled(rows, changes, DEC1)],
                         [Decimal("1.80"), Decimal("1.60")])

    def test_held_changes_are_ignored(self):
        rows = [_row(1, 10, "1.50")]
        changes = [_change(10, spl.TIPO_AUMENTO, "3.00", stato=spl.STATO_TRATTENUTO)]
        self.assertEqual(forecast.apply_scheduled(rows, changes, DEC1)[0].prezzo_pattuito, Decimal("1.50"))

    def test_closed_product_leaves_the_comparison(self):
        rows = [_row(1, 10, "1.50"), _row(2, 20, "1.60")]
        self.assertEqual([r.fornitore_id for r in forecast.apply_scheduled(rows, [_change(10, spl.TIPO_NON_TRATTATO)], DEC1)],
                         [20])

    def test_change_on_another_variant_does_not_touch_this_one(self):
        rows = [_row(1, 10, "1.50", alias=7)]
        self.assertEqual(forecast.apply_scheduled(rows, [_change(10, spl.TIPO_AUMENTO, "2", alias=8)], DEC1)[0].prezzo_pattuito,
                         Decimal("1.50"))


class BestSupplierTest(unittest.TestCase):
    def test_cheapest_variant_per_supplier_and_best_overall(self):
        rows = [_row(1, 10, "1.80"), _row(2, 10, "1.70", alias=5), _row(3, 20, "1.65")]
        with patch.object(forecast, "comparable_listino_price", lambda row, product, alias=None: row.prezzo_pattuito):
            result = forecast.forecast_for_product(rows, SimpleNamespace(comparison_unit="Kg"), {}, DEC1)
        self.assertEqual(result.prezzi, {10: Decimal("1.70"), 20: Decimal("1.65")})
        self.assertEqual(result.migliore, 20)

    def test_rows_not_comparable_are_left_out(self):
        with patch.object(forecast, "comparable_listino_price", lambda row, product, alias=None: None):
            result = forecast.forecast_for_product([_row(1, 10, "1")], SimpleNamespace(comparison_unit="Kg"), {}, DEC1)
        self.assertIsNone(result.migliore)


class AfterIncreaseTest(unittest.TestCase):
    def test_another_supplier_becomes_cheaper(self):
        f = forecast.Forecast(giorno=DEC1, prezzi={10: Decimal("1.80"), 20: Decimal("1.65")}, unita_confronto="Kg")
        change = SimpleNamespace(fornitore_id=10)
        result = links.after_increase(f, change, Decimal("1200"), {20: SimpleNamespace(nome_azienda="Rossi")})
        self.assertFalse(result["resta_il_migliore"])
        self.assertEqual((result["migliore_fornitore"], result["migliore_prezzo"]), ("Rossi", "1.65"))
        self.assertEqual(result["risparmio_annuo"], "100.00")  # 1200 × (1,80 − 1,65) / 1,80

    def test_still_the_cheapest(self):
        f = forecast.Forecast(giorno=DEC1, prezzi={10: Decimal("1.60"), 20: Decimal("1.65")})
        result = links.after_increase(f, SimpleNamespace(fornitore_id=10), Decimal("1200"), {10: SimpleNamespace(nome_azienda="Ma.Gi.Fer.")})
        self.assertTrue(result["resta_il_migliore"])
        self.assertIsNone(result["risparmio_annuo"])

    def test_nothing_comparable(self):
        self.assertIsNone(links.after_increase(forecast.Forecast(giorno=DEC1), SimpleNamespace(fornitore_id=10), None, {}))


class PriceDayTest(unittest.TestCase):
    def test_delivery_day_never_before_today(self):
        today = date(2026, 11, 19)
        self.assertEqual(forecast.price_day("2026-12-02", today), date(2026, 12, 2))
        self.assertEqual(forecast.price_day("2026-11-01", today), today)
        self.assertEqual(forecast.price_day("domani", today), today)
        self.assertEqual(forecast.price_day(None, today), today)

    def test_database_row_is_copied_not_changed(self):
        from app.models.listino import ListinoMaster
        row = ListinoMaster(id=1, fornitore_id=10, sku_interno="ZUC", prezzo_pattuito=Decimal("1.50"), unita_misura="kg",
                            data_inizio_validita=date(2026, 11, 1), descrizione="Zucchine")
        [copy] = forecast.apply_scheduled([row], [_change(10, spl.TIPO_AUMENTO, "1.80")], DEC1)
        self.assertEqual((copy.prezzo_pattuito, copy.descrizione, copy.data_inizio_validita),
                         (Decimal("1.80"), "Zucchine", date(2026, 11, 1)))
        self.assertEqual(row.prezzo_pattuito, Decimal("1.50"))


class OrdersReadDeliveryDayTest(unittest.TestCase):
    def test_sector_draft_and_save_use_the_same_day(self):
        from app.api.v1 import ordini
        for function in (ordini.elabora_ordine_settore, ordini.salva_ordini_settore):
            source = inspect.getsource(function)
            self.assertIn("price_day(data.data_consegna", source, function.__name__)
            self.assertIn("with_scheduled(db,", source, function.__name__)
            self.assertNotIn("data_inizio_validita <= today", source, function.__name__)


class SmartSheetTest(unittest.TestCase):
    def test_matrix_reads_prices_on_the_requested_day(self):
        from app.api.v1 import smart_price_sheet as sheet
        source = inspect.getsource(sheet.matrix)
        self.assertIn("price_on = max(data, today)", source)
        self.assertIn("with_scheduled(db, active_prices, price_on)", source)
        # L'Excel chiama matrix() direttamente: deve passare data=None, non il default di Query.
        self.assertIn("data=None", inspect.getsource(sheet.matrix_export))

    def test_upcoming_best_change_is_marked(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from app.api.v1 import smart_price_sheet as sheet
        db = MagicMock()
        result = MagicMock()
        result.all.return_value = [("ZUC", DEC1), ("POM", DEC1)]
        db.execute = AsyncMock(return_value=result)
        future = {"ZUC": forecast.Forecast(giorno=DEC1, prezzi={10: Decimal("1.80"), 20: Decimal("1.65")}),
                  "POM": forecast.Forecast(giorno=DEC1, prezzi={10: Decimal("1.00"), 20: Decimal("1.65")})}
        rows = [{"sku_interno": "ZUC", "absolute_cheapest_supplier_id": 10},
                {"sku_interno": "POM", "absolute_cheapest_supplier_id": 10}]
        with patch.object(sheet, "forecast_on", AsyncMock(return_value=future)):
            asyncio.run(sheet._mark_upcoming_best_change(db, rows, date(2026, 11, 19), {20: "Rossi"}))
        self.assertEqual(rows[0]["cambio_migliore"]["fornitore"], "Rossi")
        self.assertEqual(rows[0]["cambio_migliore"]["dal"], "2026-12-01")
        self.assertNotIn("cambio_migliore", rows[1])


class DecreaseIsImmediateTest(unittest.TestCase):
    def test_submit_applies_decreases_right_away(self):
        source = inspect.getsource(links.submit_open_price_list)
        self.assertIn("decision.decorrenza <= today", source)
        self.assertIn("apply_change_now(db, change.id", source)


class PricesDoNotExpireTest(unittest.TestCase):
    def test_form_approval_keeps_prices_open(self):
        from app.api.v1 import supplier_price_forms as forms
        self.assertNotIn("data_scadenza = request.validita_inviata_a", inspect.getsource(forms.approve_form_request))

    def test_suppliers_to_remind(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        today = date(2026, 12, 2)
        result = MagicMock()
        result.all.return_value = [
            (1, "approved", date(2026, 11, 22)), (1, "approved", date(2026, 11, 29)),  # scaduto: sollecitare
            (2, "approved", date(2026, 11, 29)), (2, "submitted", None),            # risposta in attesa
            (3, "approved", date(2026, 12, 6)),                                      # ancora valido
            (4, "approved", None),                                                   # senza data di fine
        ]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)
        self.assertEqual(asyncio.run(links.expired_form_suppliers(db, today)), {1: date(2026, 11, 29)})


if __name__ == "__main__":
    unittest.main()
