"""Listino Smart: acquisti, spesa e ultimo acquisto per voce, ordinamento della matrice.

Nessun database: regole Python su righe sintetiche e SQL compilato per PostgreSQL.
Il percorso completo su PostgreSQL usa e getta e' in smart_price_sheet_purchases_e2e.py.
"""
import os
import re
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

from app.models.fatture import TipoDocumento  # noqa: E402
from app.models.products import Product  # noqa: E402
from app.services import smart_price_purchases as spp  # noqa: E402


def sql(statement) -> str:
    text = " ".join(str(statement.compile(dialect=postgresql.dialect())).split())
    return re.sub(r"%\(\w+\)s", "?", text)


def line(fattura, sku, qty, price, tipo=TipoDocumento.TD01, sconto="0", omaggio=False, day=1):
    return SimpleNamespace(
        sku_interno=sku, fattura_id=fattura, data_documento=date(2026, 3, day), tipo_documento=tipo,
        prezzo_unitario=Decimal(price), sconto_percentuale=Decimal(sconto), quantita=Decimal(qty),
        is_omaggio=omaggio,
    )


TENANT_1 = SimpleNamespace(id=1, tenant_id=1)


class PurchaseStatsRulesTest(unittest.TestCase):
    def test_counts_distinct_invoices_and_signed_spend(self):
        stats = spp.purchase_stats_from_lines([
            line(1, "TOVAGLIOLI", "10", "2.00", day=1),
            line(1, "TOVAGLIOLI", "5", "2.00", day=1),          # stessa fattura: un solo acquisto
            line(2, "TOVAGLIOLI", "10", "2.00", sconto="10", day=5),
            line(3, "TOVAGLIOLI", "4", "2.00", tipo=TipoDocumento.TD04, day=9),  # nota di credito
        ])["TOVAGLIOLI"]
        self.assertEqual(stats.acquisti, 2)
        # 30 + 18 - 8
        self.assertEqual(stats.spesa, Decimal("40.00"))
        self.assertEqual(stats.ultimo_acquisto, date(2026, 3, 5))

    def test_credit_notes_and_gifts_are_not_purchases(self):
        stats = spp.purchase_stats_from_lines([
            line(7, "BICCHIERI", "1", "3", tipo=TipoDocumento.TD08, day=20),
            line(8, "BICCHIERI", "2", "0", day=21),                 # omaggio a prezzo 0
            line(9, "BICCHIERI", "2", "5", sconto="100", day=22),   # omaggio sconto 100%
            line(10, "BICCHIERI", "2", "5", omaggio=True, day=23),  # omaggio da XML
        ])["BICCHIERI"]
        self.assertEqual(stats.acquisti, 0)
        self.assertIsNone(stats.ultimo_acquisto)
        self.assertEqual(stats.spesa, Decimal("7"))  # -3 della TD08 + 10 della riga omaggio con prezzo

    def test_sort_keys(self):
        stats = {
            "A": spp.PurchaseStats(acquisti=3, spesa=Decimal("10")),
            "B": spp.PurchaseStats(acquisti=3, spesa=Decimal("50")),
            "C": spp.PurchaseStats(acquisti=1, spesa=Decimal("900")),
        }
        names = ["A", "B", "C", "D"]
        self.assertEqual(sorted(names, key=lambda n: spp.sort_key("acquisti", n, stats.get(n))), ["B", "A", "C", "D"])
        self.assertEqual(sorted(names, key=lambda n: spp.sort_key("spesa", n, stats.get(n))), ["C", "B", "A", "D"])
        self.assertEqual(sorted(names, key=lambda n: spp.sort_key("nome", n, stats.get(n))), names)

    def test_payload(self):
        self.assertEqual(spp.stats_payload(None, None, None), {"acquisti": 0, "spesa": "0.00", "ultimo_acquisto": None})
        self.assertEqual(spp.stats_payload(4, Decimal("12.345"), date(2026, 1, 2))["ultimo_acquisto"], "2026-01-02")

    def test_period(self):
        self.assertIsNone(spp.period_start("tutto", date(2026, 11, 16)))
        self.assertEqual(spp.period_start("12m", date(2026, 11, 16)), date(2025, 11, 16))


class PurchaseStatsSqlTest(unittest.TestCase):
    def test_aggregate_uses_shared_base(self):
        text = sql(spp.purchase_stats_select(TENANT_1, location_id=2, date_from=date(2025, 11, 16)))
        self.assertIn("count(DISTINCT righe_acquisto.fattura_id) FILTER (WHERE righe_acquisto.in_media)", text)
        self.assertIn("max(righe_acquisto.data_documento) FILTER (WHERE righe_acquisto.in_media)", text)
        self.assertIn("sum(righe_acquisto.importo_netto)", text)
        self.assertIn("skus_esclusi", text)
        self.assertIn("righe_escluse_statistiche", text)
        self.assertIn("fatture.tenant_id", text)
        self.assertIn("fatture.location_id IN", text)
        self.assertIn("fatture.data_documento >=", text)
        self.assertIn("GROUP BY righe_acquisto.sku_interno", text)
        # in_media esclude note di credito e omaggi; importo_netto ha il segno -1 per TD04/TD08.
        self.assertIn("fatture.tipo_documento NOT IN", text)
        self.assertNotIn("prezzo_netto_normalizzato", text)

    def test_sort_by_purchases_orders_before_limit(self):
        stats = spp.purchase_stats_select(TENANT_1).subquery("acquisti_voce")
        text = sql(spp.matrix_page_select([Product.is_active.is_(True)], "acquisti", stats).limit(500))
        self.assertIn("LEFT OUTER JOIN", text)
        order = text.index("ORDER BY coalesce(acquisti_voce.acquisti, ?) DESC, coalesce(acquisti_voce.spesa, ?) DESC, products.canonical_name, products.id")
        self.assertLess(order, text.index("LIMIT"))

    def test_sort_by_spend(self):
        stats = spp.purchase_stats_select(TENANT_1).subquery("acquisti_voce")
        text = sql(spp.matrix_page_select([], "spesa", stats))
        self.assertIn("ORDER BY coalesce(acquisti_voce.spesa, ?) DESC, coalesce(acquisti_voce.acquisti, ?) DESC", text)

    def test_sort_by_name_is_unchanged(self):
        filters = [Product.is_active.is_(True)]
        before = select(Product).where(*filters).order_by(Product.canonical_name, Product.id).limit(100).offset(0)
        after = spp.matrix_page_select(filters, "nome").limit(100).offset(0)
        self.assertEqual(sql(after), sql(before))
        self.assertEqual(sql(spp.matrix_page_select(filters, "nome", object())), sql(spp.matrix_page_select(filters, "nome")))


if __name__ == "__main__":
    unittest.main()
