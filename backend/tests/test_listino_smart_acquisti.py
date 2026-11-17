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
from app.models.products import Product, SupplierProductAlias  # noqa: E402
from app.services import purchase_lines as pl  # noqa: E402
from app.services import smart_price_purchases as spp  # noqa: E402
from app.services.normalization import normalize_text  # noqa: E402


def sql(statement) -> str:
    text = " ".join(str(statement.compile(dialect=postgresql.dialect())).split())
    return re.sub(r"%\(\w+\)s", "?", text)


def line(fattura, sku, qty, price, tipo=TipoDocumento.TD01, sconto="0", omaggio=False, day=1,
         fornitore=9, product_id=None, codice=None, descrizione="", uom="PZ"):
    return SimpleNamespace(
        sku_interno=sku, fattura_id=fattura, data_documento=date(2026, 3, day), tipo_documento=tipo,
        prezzo_unitario=Decimal(price), sconto_percentuale=Decimal(sconto), quantita=Decimal(qty),
        is_omaggio=omaggio, fornitore_id=fornitore, product_id=product_id, codice_fornitore=codice,
        descrizione=descrizione, unita_misura=uom,
    )


# Voci reali (export di produzione): panino a cartone da 100, buste a cartone.
PANINO = Product(id=1, sku_interno="PANINO", canonical_name="MINI PANINO", comparison_unit="Pz", unit_count=1)
PANINO_DESC = "PANINO EDNA PARTY BURGER MIX GR.30(CF.100PZ) GELO"
BUSTE = Product(id=2, sku_interno="BUSTE", canonical_name="BUSTE AMBRA", comparison_unit="CT", unit_count=1)
BUSTE_DESC = "Buste ambra N.U. PE/LD cm 90x120h 18kg"
PANINO_ALIAS = SupplierProductAlias(
    id=10, supplier_id=9, product_id=1, supplier_code="PPANVE", raw_description=PANINO_DESC,
    normalized_description=normalize_text(PANINO_DESC), pack_qty=100, status="approved", source="manual",
)


def conversions_for(lines):
    keys = {pl.conversion_key(item) for item in lines}
    return pl.compute_conversions(keys, {1: PANINO, 2: BUSTE}, pl.AliasIndex([PANINO_ALIAS]))


def panino(fattura, qty, uom="CT", **kw):
    return line(fattura, "PANINO", qty, kw.pop("price", "25.90"), product_id=1, codice="PPANVE",
                descrizione=PANINO_DESC, uom=uom, **kw)


def buste(fattura, qty, uom="CT", **kw):
    return line(fattura, "BUSTE", qty, kw.pop("price", "30.42"), product_id=2, descrizione=BUSTE_DESC, uom=uom, **kw)


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
        self.assertEqual(spp.stats_payload(None, None, None), {
            "acquisti": 0, "spesa": "0.00", "ultimo_acquisto": None,
            "quantita": "0", "quantita_unita": None, "quantita_non_convertita": {},
        })
        self.assertEqual(spp.stats_payload(4, Decimal("12.345"), date(2026, 1, 2))["ultimo_acquisto"], "2026-01-02")

    def test_period(self):
        self.assertIsNone(spp.period_start("tutto", date(2026, 11, 16)))
        self.assertEqual(spp.period_start("12m", date(2026, 11, 16)), date(2025, 11, 16))


class PurchaseQuantityTest(unittest.TestCase):
    def test_carton_converted_to_pieces(self):
        lines = [panino(1, "3"), panino(2, "2", uom="CT")]
        stats = spp.purchase_stats_from_lines(lines, conversions_for(lines))["PANINO"]
        self.assertEqual(stats.quantita, Decimal("500"))  # 5 cartoni da 100 pezzi
        self.assertEqual(stats.quantita_non_convertita, {})

    def test_credit_notes_are_negative(self):
        lines = [panino(1, "3"), panino(2, "1", tipo=TipoDocumento.TD04), panino(3, "1", tipo=TipoDocumento.TD08)]
        stats = spp.purchase_stats_from_lines(lines, conversions_for(lines))["PANINO"]
        self.assertEqual(stats.quantita, Decimal("100"))
        self.assertEqual(stats.acquisti, 1)

    def test_gifts_are_not_counted(self):
        lines = [
            panino(1, "2"),
            panino(2, "5", price="0"),
            panino(3, "5", sconto="100"),
            panino(4, "5", omaggio=True),
        ]
        stats = spp.purchase_stats_from_lines(lines, conversions_for(lines))["PANINO"]
        self.assertEqual(stats.quantita, Decimal("200"))

    def test_unreliable_lines_are_kept_apart_by_invoice_unit(self):
        lines = [
            buste(1, "4"),                                   # cartoni: 4 CT
            buste(2, "30", uom="K.", price="1.57"),          # kg per cartone non noti
            buste(3, "10", uom="KGM", price="1.57"),
            buste(4, "4", uom="NR", price="2"),              # pezzi per cartone non noti
            buste(5, "5", uom="KG", price="1.57", tipo=TipoDocumento.TD04),
        ]
        stats = spp.purchase_stats_from_lines(lines, conversions_for(lines))["BUSTE"]
        self.assertEqual(stats.quantita, Decimal("4"))
        self.assertEqual(stats.quantita_non_convertita, {"KG": Decimal("35"), "PZ": Decimal("4")})
        payload = spp.stats_payload(stats.acquisti, stats.spesa, None, stats.quantita,
                                    stats.quantita_non_convertita, "CT")
        self.assertEqual(payload["quantita"], "4")
        self.assertEqual(payload["quantita_unita"], "CT")
        self.assertEqual(payload["quantita_non_convertita"], {"KG": "35", "PZ": "4"})

    def test_unit_cancelled_by_credit_note_disappears(self):
        lines = [buste(1, "3", uom="KG", price="1.5"), buste(2, "3", uom="KG", price="1.5", tipo=TipoDocumento.TD04)]
        stats = spp.purchase_stats_from_lines(lines, conversions_for(lines))["BUSTE"]
        self.assertEqual(stats.quantita_non_convertita, {})

    def test_quantity_text(self):
        self.assertEqual(spp.quantity_text(Decimal("312.00000000")), "312")
        self.assertEqual(spp.quantity_text(Decimal("35.50000")), "35.5")
        self.assertEqual(spp.quantity_text(Decimal("-2.0")), "-2")
        self.assertEqual(spp.quantity_text(None), "0")
        self.assertEqual(spp.stats_payload(1, 1, None, "12.5", {"KG": "0.000", "PZ": "4.000"}, "Kg")["quantita_non_convertita"],
                         {"PZ": "4"})

    def test_sort_by_quantity_then_purchases(self):
        stats = {
            "A": spp.PurchaseStats(acquisti=1, quantita=Decimal("300")),
            "B": spp.PurchaseStats(acquisti=5, quantita=Decimal("300")),
            "C": spp.PurchaseStats(acquisti=9, quantita=Decimal("12")),
        }
        names = ["A", "B", "C", "D"]
        self.assertEqual(sorted(names, key=lambda n: spp.sort_key("quantita", n, stats.get(n))), ["B", "A", "C", "D"])


class PurchaseStatsSqlTest(unittest.TestCase):
    def test_quantity_uses_conversion_table(self):
        key = pl.ConversionKey(9, 1, "PPANVE", PANINO_DESC, "CT")
        conversions = pl.compute_conversions([key], {1: PANINO}, pl.AliasIndex([PANINO_ALIAS]))
        text = " ".join(str(spp.purchase_stats_select(TENANT_1, conversions=conversions).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).split())
        self.assertIn("conv_acquisti_values", text)
        self.assertIn("CASE WHEN (conv_acquisti.reliable IS true) THEN righe_acquisto.quantita_firmata * conv_acquisti.factor", text)
        self.assertIn("FILTER (WHERE righe_acquisto.is_omaggio IS false)", text)
        self.assertIn("conv_acquisti.reliable IS NOT true", text)
        self.assertIn("jsonb_object_agg(non_convertite_unita.unita", text)
        self.assertIn("GROUP BY righe_acquisto.sku_interno, righe_acquisto.unita", text)
        self.assertIn("righe_escluse_statistiche", text)
        self.assertIn("fatture.tenant_id", text)

    def test_sort_by_quantity_orders_before_limit(self):
        stats = spp.purchase_stats_select(TENANT_1).subquery("acquisti_voce")
        text = sql(spp.matrix_page_select([], "quantita", stats).limit(100))
        order = text.index("ORDER BY coalesce(acquisti_voce.quantita, ?) DESC, coalesce(acquisti_voce.acquisti, ?) DESC, products.canonical_name, products.id")
        self.assertLess(order, text.index("LIMIT"))
        self.assertIn("acquisti_voce.quantita_non_convertita", text)

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


class MonthsBeforeTest(unittest.TestCase):
    """Periodo del pulsante «Solo i più acquistati» nei moduli fornitori."""

    def test_same_day_months_before(self):
        self.assertEqual(spp.months_before(date(2026, 11, 17), 12), date(2025, 11, 17))
        self.assertEqual(spp.months_before(date(2026, 11, 17), 3), date(2026, 8, 17))
        self.assertEqual(spp.months_before(date(2026, 2, 10), 2), date(2025, 12, 10))

    def test_end_of_month_when_day_missing(self):
        self.assertEqual(spp.months_before(date(2026, 3, 31), 1), date(2026, 2, 28))
        self.assertEqual(spp.months_before(date(2028, 3, 31), 1), date(2028, 2, 29))
        self.assertEqual(spp.months_before(date(2026, 12, 31), 1), date(2026, 11, 30))


if __name__ == "__main__":
    unittest.main()
