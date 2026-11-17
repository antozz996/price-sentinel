"""Listino sempre aperto: date fisse, ribassi, aumenti, sospensioni e tabelle.

Nessun database: regole Python e struttura delle tabelle.
"""
import os
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal as D

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

import app.models  # noqa: E402,F401
from app.models import supplier_price_link as spl  # noqa: E402
from app.services import open_price_list_rules as rules  # noqa: E402

OGGI = date(2026, 11, 17)


def decide(old, new, **kw):
    return rules.decide_change(today=kw.pop("today", OGGI), prezzo_vecchio=old, prezzo_nuovo=new, **kw)


class NextFixedDateTest(unittest.TestCase):
    def test_first_half_goes_to_15(self):
        self.assertEqual(rules.next_fixed_date(date(2026, 11, 2)), date(2026, 11, 15))
        self.assertEqual(rules.next_fixed_date(date(2026, 11, 14)), date(2026, 11, 15))

    def test_on_fixed_date_goes_to_next_one(self):
        # Il listino va consegnato prima della data: caricato il 15 vale dal 1.
        self.assertEqual(rules.next_fixed_date(date(2026, 11, 15)), date(2026, 12, 1))
        self.assertEqual(rules.next_fixed_date(date(2026, 11, 1)), date(2026, 11, 15))

    def test_year_change(self):
        self.assertEqual(rules.next_fixed_date(date(2026, 12, 20)), date(2027, 1, 1))

    def test_today_rome_uses_italian_date(self):
        # 23:30 UTC del 30/11 è già il 1/12 in Italia.
        self.assertEqual(rules.today_rome(datetime(2026, 11, 30, 23, 30, tzinfo=timezone.utc)), date(2026, 12, 1))


class DecideChangeTest(unittest.TestCase):
    def test_decrease_is_immediate(self):
        d = decide(D("10"), D("9"))
        self.assertEqual((d.tipo, d.stato, d.decorrenza), (spl.TIPO_RIBASSO, spl.STATO_PROGRAMMATO, OGGI))

    def test_increase_waits_for_fixed_date(self):
        d = decide(D("10"), D("11"))
        self.assertEqual((d.tipo, d.stato, d.decorrenza), (spl.TIPO_AUMENTO, spl.STATO_PROGRAMMATO, date(2026, 12, 1)))

    def test_big_decrease_is_held(self):
        d = decide(D("10"), D("5.90"))
        self.assertEqual((d.tipo, d.stato), (spl.TIPO_RIBASSO, spl.STATO_TRATTENUTO))
        self.assertIn("40%", d.motivo_trattenuta)

    def test_decrease_of_exactly_40_is_not_held(self):
        self.assertEqual(decide(D("10"), D("6")).stato, spl.STATO_PROGRAMMATO)

    def test_big_increase_is_held_but_keeps_fixed_date(self):
        d = decide(D("10"), D("13.10"))
        self.assertEqual((d.tipo, d.stato, d.decorrenza), (spl.TIPO_AUMENTO, spl.STATO_TRATTENUTO, date(2026, 12, 1)))
        self.assertIn("30%", d.motivo_trattenuta)

    def test_increase_of_exactly_30_is_not_held(self):
        self.assertEqual(decide(D("10"), D("13")).stato, spl.STATO_PROGRAMMATO)

    def test_same_price_saves_nothing(self):
        d = decide(D("10"), D("10.0000"))
        self.assertEqual((d.tipo, d.stato), (spl.TIPO_INVARIATO, None))

    def test_new_offer_is_immediate(self):
        d = decide(None, D("4"))
        self.assertEqual((d.tipo, d.stato, d.decorrenza), (spl.TIPO_NUOVA_OFFERTA, spl.STATO_PROGRAMMATO, OGGI))

    def test_extra_offer_on_quoted_product_is_held(self):
        d = decide(None, D("4"), altra_offerta_attiva=True)
        self.assertEqual((d.tipo, d.stato), (spl.TIPO_NUOVA_OFFERTA, spl.STATO_TRATTENUTO))

    def test_not_handled_closes_at_next_fixed_date(self):
        d = decide(D("10"), None, non_trattato=True)
        self.assertEqual((d.tipo, d.stato, d.decorrenza), (spl.TIPO_NON_TRATTATO, spl.STATO_PROGRAMMATO, date(2026, 12, 1)))

    def test_missing_or_zero_price_is_rejected(self):
        for value in (None, D("0"), D("-1")):
            with self.assertRaises(ValueError):
                decide(D("10"), value)


class TablesTest(unittest.TestCase):
    def test_offer_key(self):
        self.assertEqual(spl.offer_key("GIN", 7), "GIN#7")
        self.assertEqual(spl.offer_key("GIN", None), "GIN#")

    def test_one_pending_change_per_offer(self):
        index = next(i for i in spl.SupplierPriceChange.__table__.indexes
                     if i.name == "uq_supplier_price_change_in_attesa")
        self.assertTrue(index.unique)
        self.assertEqual([c.name for c in index.columns], ["fornitore_id", "chiave_offerta"])
        where = str(index.dialect_options["postgresql"]["where"])
        for stato in spl.STATI_IN_ATTESA:
            self.assertIn(f"'{stato}'", where)

    def test_one_active_link_per_supplier(self):
        index = next(i for i in spl.SupplierPriceLink.__table__.indexes if i.name == "uq_supplier_price_link_attivo")
        self.assertTrue(index.unique)

    def test_states_and_types_fit_columns(self):
        for value in spl.STATI_MODIFICA + spl.TIPI_MODIFICA:
            self.assertLessEqual(len(value), 20)

    def test_lock_key_is_stable_and_per_offer(self):
        self.assertEqual(rules.offer_lock_key(1, "GIN#"), rules.offer_lock_key(1, "GIN#"))
        self.assertNotEqual(rules.offer_lock_key(1, "GIN#"), rules.offer_lock_key(2, "GIN#"))
        self.assertTrue(-(2 ** 63) <= rules.offer_lock_key(1, "GIN#") < 2 ** 63)


if __name__ == "__main__":
    unittest.main()
