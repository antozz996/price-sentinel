"""Listino sempre aperto: attivazione delle modifiche alla loro data (senza database)."""
import inspect
import os
import unittest
from datetime import date
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from app import main  # noqa: E402
from app.models.listino import ORIGINE_LISTINO_APERTO, ORIGINI_PREZZO, ListinoMaster, PFAScaglione, UoMConversione  # noqa: E402
from app.models.supplier_price_link import (  # noqa: E402
    TIPO_AUMENTO, TIPO_NON_TRATTATO, TIPO_RIBASSO, SupplierPriceChange,
)
from app.services import open_price_list_activation as act  # noqa: E402

D = date


class PlanTest(unittest.TestCase):
    def plan(self, **kw):
        base = dict(tipo=TIPO_AUMENTO, decorrenza=D(2026, 12, 1), inizio=D(2026, 1, 10), scadenza=None,
                    riga_piu_recente=False)
        return act.plan_listino_update(**{**base, **kw})

    def test_increase_closes_old_row_the_day_before(self):
        plan = self.plan()
        self.assertTrue(plan.applicabile)
        self.assertEqual(plan.chiudi_al, D(2026, 11, 30))
        self.assertEqual(plan.nuova_dal, D(2026, 12, 1))
        self.assertIsNone(plan.nuova_al)

    def test_backlog_keeps_its_own_date(self):
        plan = self.plan(tipo=TIPO_RIBASSO, decorrenza=D(2026, 11, 3))
        self.assertEqual((plan.chiudi_al, plan.nuova_dal), (D(2026, 11, 2), D(2026, 11, 3)))

    def test_not_handled_only_closes(self):
        plan = self.plan(tipo=TIPO_NON_TRATTATO)
        self.assertEqual(plan.chiudi_al, D(2026, 11, 30))
        self.assertIsNone(plan.nuova_dal)

    def test_newer_upload_wins(self):
        self.assertFalse(self.plan(riga_piu_recente=True).applicabile)

    def test_row_expired_before_start_is_not_reopened(self):
        self.assertFalse(self.plan(scadenza=D(2026, 11, 20)).applicabile)

    def test_weekly_row_keeps_its_end(self):
        plan = self.plan(decorrenza=D(2026, 11, 17), inizio=D(2026, 11, 10), scadenza=D(2026, 11, 23))
        self.assertEqual((plan.chiudi_al, plan.nuova_dal, plan.nuova_al),
                         (D(2026, 11, 16), D(2026, 11, 17), D(2026, 11, 23)))

    def test_no_inverted_interval(self):
        plan = self.plan(decorrenza=D(2026, 11, 17), inizio=D(2026, 11, 17))
        self.assertEqual(plan.chiudi_al, D(2026, 11, 17))


class CopyRowTest(unittest.TestCase):
    def test_new_row_keeps_unit_alias_discounts_and_conversions(self):
        origin = ListinoMaster(
            id=7, fornitore_id=3, sku_interno="GIN-70", descrizione="Gin 70cl", prezzo_pattuito=Decimal("10"),
            unita_misura="Pz", data_inizio_validita=D(2026, 1, 1), supplier_product_alias_id=11,
            pfa_tipo=None, pfa_valore=None,
        )
        origin.pfa_scaglioni = [PFAScaglione(soglia_da=0, soglia_a=None, valore_percentuale=Decimal("0.02"))]
        origin.uom_conversioni = [UoMConversione(uom_fattura="CT", coefficiente=Decimal("6"))]
        change = SupplierPriceChange(prezzo_nuovo=Decimal("11.5"), unita_misura="Pz")
        plan = act.ListinoPlan(applicabile=True, chiudi_al=D(2026, 11, 30), nuova_dal=D(2026, 12, 1))
        row = act._copy_row(origin, change, plan)
        self.assertEqual(row.prezzo_pattuito, Decimal("11.5"))
        self.assertEqual((row.unita_misura, row.supplier_product_alias_id), ("Pz", 11))
        self.assertEqual(row.origine, ORIGINE_LISTINO_APERTO)
        self.assertEqual(row.data_inizio_validita, D(2026, 12, 1))
        self.assertEqual(len(row.pfa_scaglioni), 1)
        self.assertEqual(row.uom_conversioni[0].coefficiente, Decimal("6"))
        self.assertIsNot(row.uom_conversioni[0], origin.uom_conversioni[0])


class WiringTest(unittest.TestCase):
    def test_origin_is_registered(self):
        self.assertIn(ORIGINE_LISTINO_APERTO, ORIGINI_PREZZO)

    def test_loop_runs_activation_in_its_own_transaction(self):
        source = inspect.getsource(main._automation_loop)
        self.assertIn("apply_due_price_changes(session)", source)
        self.assertLess(source.index("run_operational_monitor"), source.index("apply_due_price_changes"))

    def test_activation_runs_once_a_day(self):
        source = inspect.getsource(main._automation_loop)
        self.assertIn("if last_activation_day != date.today():", source)
        self.assertLess(source.index("apply_due_price_changes"), source.index("last_activation_day = date.today()"))

    def test_offer_lock_taken_before_row_lock(self):
        source = inspect.getsource(act._apply_one)
        self.assertLess(source.index("pg_advisory_xact_lock"), source.index("with_for_update=True"))

    def test_only_due_scheduled_changes(self):
        source = inspect.getsource(act.apply_due_price_changes)
        self.assertIn("STATO_PROGRAMMATO", source)
        self.assertIn("decorrenza <= today", source)
        self.assertIn("pg_try_advisory_xact_lock", source)


if __name__ == "__main__":
    unittest.main()
