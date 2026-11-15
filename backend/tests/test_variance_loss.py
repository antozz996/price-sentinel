"""Dashboard: analisi sprechi e classifica efficienza (services/variance_loss.py).

Righe reali di produzione (export del 14/11/2026, fatture caricate dal 06/11/2026,
senza le 39 fatture doppie e senza note di credito): MINI PANINO EDNA (MELIUS, a
cartone da 100) e SACCHI 90X120 AMBRA (KITO, VE.MO, ALFA, EUROCARTA). Nessun database.
"""
import os
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from sqlalchemy.dialects import postgresql  # noqa: E402

from app.models.products import Product, SupplierProductAlias  # noqa: E402
from app.services import variance_loss as vl  # noqa: E402
from app.services.purchase_lines import AliasIndex, line_net_unit_price  # noqa: E402
from app.services.normalization import normalize_text  # noqa: E402

ADMIN = SimpleNamespace(id=1, tenant_id=1)
MINI_PANINO_SKU = "SG3-52506F3CBE1143E1"
SACCHI_SKU = "SG3-165D17EA2619C309"


def sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def expand(sku, name, supplier, unit, groups):
    """groups: (quantità, prezzo unitario, sconto %, numero di righe uguali)."""
    lines = []
    for quantity, price, discount, count in groups:
        for _ in range(count):
            lines.append(vl.WasteLine(
                riga_id=len(lines) + 1, sku_interno=sku, unita=unit, fornitore=supplier, prodotto_nome=name,
                quantita=Decimal(quantity), netto_unitario=line_net_unit_price(price, discount),
            ))
    return lines


# 49 righe MELIUS a cartone nel periodo (tutte prima del listino del 27/10/2026, tranne una).
MINI_PANINO_ROWS = expand(MINI_PANINO_SKU, "MINI PANINO EDNA BURGHER", "MELIUS CATERING S.P.A.", "CT", [
    ("1", "25.9824", "0.0092", 2), ("1", "26.2361", "0", 2), ("1", "26.5", "0", 1), ("1", "26.6", "0", 1),
    ("1", "26.986", "0", 1), ("2", "26.0344", "0", 3), ("2", "26.2362", "0.0046", 1), ("2", "26.298", "0", 1),
    ("2", "26.36", "0", 1), ("2", "26.365", "0", 1), ("2", "26.5", "0", 1), ("2", "26.526", "0.0038", 1),
    ("2", "26.6", "0", 1), ("2", "26.6398", "0", 1), ("2", "26.826", "0.0037", 1), ("2", "26.89", "0", 1),
    ("2", "26.9", "0", 2), ("2", "26.98", "0", 3), ("2", "26.9826", "0", 3), ("2", "26.986", "0.0037", 3),
    ("3", "26.36", "0", 1), ("3", "26.5", "0", 4), ("3", "26.8926", "0", 1), ("3", "26.9", "0", 1),
    ("3", "26.98", "0", 3), ("3", "26.986", "0", 1), ("3", "26.998", "0.0049", 1), ("4", "26.36", "0", 1),
    ("4", "26.6398", "0", 1), ("4", "26.986", "0.0037", 2), ("40", "26.5", "0", 1), ("6", "26.9826", "0", 1),
])
# Minimo pagato a cartone: riga 6033 FGA del 21/10/2026. Le 17 righe FGA con
# prezzo_netto_normalizzato sovrascritto a 0,259 hanno pu ~26,6 a cartone.
MINI_PANINO_MIN = {(MINI_PANINO_SKU, "CT"): Decimal("25.90")}

SACCHI = "SACCHI X RAC. RIFIUTI MIS. 90X120 COL. AMBRA"
SACCHI_ROWS = (
    expand(SACCHI_SKU, SACCHI, "KITO SRL", "CT", [
        ("1", "24.5", "0", 2), ("2", "22.5", "0", 4), ("2", "23", "0", 5), ("2", "23.5", "0", 1),
        ("2", "23.625", "0", 1), ("3", "22.5", "0", 2), ("3", "23", "0", 4), ("4", "22.5", "0", 1),
        ("4", "23", "0", 1), ("4", "23.5", "0", 1), ("5", "22.5", "0", 1), ("5", "23", "0", 1),
    ])
    + expand(SACCHI_SKU, SACCHI, "VE.MO. HOTELLERIE S.R.L.S.", "CT", [
        ("1", "29.25", "0", 1), ("1", "30.42", "0", 2), ("2", "27", "0", 2), ("2", "28.08", "0", 3),
        ("2", "30.42", "0", 8),
    ])
    + expand(SACCHI_SKU, SACCHI, "KITO SRL", "CNF", [("2", "22.5", "0", 1), ("2", "23", "0", 1), ("4", "23.5", "0", 2)])
    + expand(SACCHI_SKU, SACCHI, "ALFA SERVICE SRL", "PZ", [("1", "24", "0", 2), ("2", "22.5", "0", 1)])
    # Riga 12602 EUROCARTA: 30 KG a 1,5667. Prima faceva da minimo per i cartoni.
    + expand(SACCHI_SKU, SACCHI, "EUROCARTA SRLS", "KG", [("30", "1.5667", "0.0021", 1)])
)
SACCHI_MIN = {
    (SACCHI_SKU, "CT"): Decimal("22.5"),
    (SACCHI_SKU, "CNF"): Decimal("22.5"),
    (SACCHI_SKU, "PZ"): Decimal("22.5"),
    (SACCHI_SKU, "KG"): line_net_unit_price("1.5667", "0.0021"),
}


def listino(lid, price, unit, start, end=None, alias_id=None):
    return SimpleNamespace(id=lid, prezzo_pattuito=Decimal(price), unita_misura=unit,
                           data_inizio_validita=start, data_scadenza=end, supplier_product_alias_id=alias_id)


class MiniPaninoTest(unittest.TestCase):
    def test_minimum_per_carton_gives_real_waste(self):
        [row] = vl.aggregate_waste(MINI_PANINO_ROWS, MINI_PANINO_MIN)
        self.assertEqual(row["numero_acquisti"], 49)
        self.assertEqual(row["unita"], "CT")
        self.assertEqual(row["prezzo_minimo"], 25.90)
        self.assertEqual(row["fonte_riferimento"], "minimo")
        self.assertAlmostEqual(row["prezzo_medio"], 26.6502, places=4)  # media pesata sulle quantità
        # Prima: minimo 0,259 (prezzo a pezzo) e 4.037,90 EUR di spreco.
        self.assertAlmostEqual(row["spreco_totale"], 114.79, places=2)

    def test_old_piece_minimum_would_inflate_waste(self):
        [row] = vl.aggregate_waste(MINI_PANINO_ROWS, {(MINI_PANINO_SKU, "CT"): Decimal("0.259")})
        self.assertGreater(row["spreco_totale"], 4000)

    def test_not_first_when_other_items_waste_more(self):
        rows = vl.aggregate_waste(MINI_PANINO_ROWS + SACCHI_ROWS, {**MINI_PANINO_MIN, **SACCHI_MIN})
        self.assertEqual(rows[0]["sku_interno"], SACCHI_SKU)


class SacchiTest(unittest.TestCase):
    def test_grouped_by_invoice_unit(self):
        rows = {row["unita"]: row for row in vl.aggregate_waste(SACCHI_ROWS, SACCHI_MIN)}
        self.assertNotIn("KG", rows)  # the only KG line is its own minimum
        self.assertAlmostEqual(rows["CT"]["spreco_totale"], 228.54, places=2)
        self.assertAlmostEqual(rows["CNF"]["spreco_totale"], 9.00, places=2)
        self.assertAlmostEqual(rows["PZ"]["spreco_totale"], 3.00, places=2)
        # Prima 2.522,27 EUR: i cartoni erano confrontati con 1,5667 al kg.
        self.assertAlmostEqual(sum(r["spreco_totale"] for r in rows.values()), 240.54, places=2)

    def test_supplier_generating_waste_comes_first(self):
        ct = next(r for r in vl.aggregate_waste(SACCHI_ROWS, SACCHI_MIN) if r["unita"] == "CT")
        self.assertEqual(ct["fornitore_nome"], "VE.MO. HOTELLERIE S.R.L.S., KITO SRL")

    def test_weighted_average_price(self):
        ct = next(r for r in vl.aggregate_waste(SACCHI_ROWS, SACCHI_MIN) if r["unita"] == "CT")
        self.assertAlmostEqual(ct["prezzo_medio"], 24.9574, places=4)
        self.assertEqual(ct["numero_acquisti"], 40)
        self.assertEqual(ct["quantita_totale"], 93.0)

    def test_limit_and_order(self):
        rows = vl.aggregate_waste(SACCHI_ROWS, SACCHI_MIN, limit=2)
        self.assertEqual([r["unita"] for r in rows], ["CT", "CNF"])


class ListinoReferenceTest(unittest.TestCase):
    MINI_PANINO = Product(id=1, sku_interno=MINI_PANINO_SKU, canonical_name="MINI PANINO EDNA BURGHER",
                          comparison_unit="Pz", unit_count=1)
    ALIAS = SupplierProductAlias(
        id=2558, supplier_id=9, product_id=1, supplier_code="PPANVE",
        raw_description="PANINO EDNA PARTY BURGER MIX GR.30(CF.100PZ) GELO",
        normalized_description=normalize_text("PANINO EDNA PARTY BURGER MIX GR.30(CF.100PZ) GELO"),
        pack_qty=100, status="approved", source="manual",
    )

    def test_valid_at_document_date(self):
        items = [listino(2, "0.25", None, date(2026, 10, 27), alias_id=2)]
        self.assertIsNone(vl.listino_valid_at(items, date(2026, 10, 21)))  # before the start
        self.assertEqual(vl.listino_valid_at(items, date(2026, 11, 3)).id, 2)
        expired = [listino(1729, "30.40", None, date(2026, 10, 27), date(2026, 11, 5))]
        self.assertIsNone(vl.listino_valid_at(expired, date(2026, 11, 6)))
        self.assertEqual(vl.listino_valid_at(expired, date(2026, 11, 5)).id, 1729)

    def test_ambiguous_listini_pick_none(self):
        items = [listino(10, "1", "Pz", date(2026, 1, 1)), listino(11, "2", "Pz", date(2026, 2, 1))]
        self.assertIsNone(vl.listino_valid_at(items, date(2026, 3, 1)))
        # The listino linked to the line's supplier article wins.
        items[1].supplier_product_alias_id = 7
        self.assertEqual(vl.listino_valid_at(items, date(2026, 3, 1), alias_id=7).id, 11)

    def test_piece_listino_converted_to_carton(self):
        conv = vl.line_conversion(product=self.MINI_PANINO, alias=self.ALIAS, unita_misura="CT",
                                  descrizione=self.ALIAS.raw_description, target_unit=None)
        price = vl.listino_price_per_invoice_unit(listino(2, "0.25", None, date(2026, 10, 27)), conv)
        self.assertEqual(price, Decimal("25.00"))

    def test_listino_takes_precedence_over_minimum(self):
        line = vl.WasteLine(1, MINI_PANINO_SKU, "CT", "MELIUS CATERING S.P.A.", "MINI PANINO", Decimal("2"),
                            Decimal("26.50"), prezzo_listino=Decimal("25.00"))
        [row] = vl.aggregate_waste([line], MINI_PANINO_MIN)
        self.assertEqual(row["fonte_riferimento"], "listino")
        self.assertEqual(row["prezzo_riferimento"], 25.0)
        self.assertEqual(row["prezzo_minimo"], 25.9)
        self.assertEqual(row["spreco_totale"], 3.0)

    def test_mixed_reference_label(self):
        lines = [
            vl.WasteLine(1, MINI_PANINO_SKU, "CT", "MELIUS", "MINI PANINO", Decimal("1"), Decimal("26.50"),
                         prezzo_listino=Decimal("25.00")),
            vl.WasteLine(2, MINI_PANINO_SKU, "CT", "MELIUS", "MINI PANINO", Decimal("1"), Decimal("26.50")),
        ]
        [row] = vl.aggregate_waste(lines, MINI_PANINO_MIN)
        self.assertEqual(row["fonte_riferimento"], "misto")
        self.assertAlmostEqual(row["spreco_totale"], 1.5 + 0.6, places=2)

    def test_unreliable_conversion_falls_back_to_minimum(self):
        # EUROCARTA 30 KG against a listino without unit on a CT item: not comparable.
        sacchi = Product(id=576, sku_interno=SACCHI_SKU, canonical_name=SACCHI, comparison_unit="CT", unit_count=1)
        rows = [SimpleNamespace(
            riga_id=12602, sku_interno=SACCHI_SKU, unita="KG", unita_misura="KG", product_id=576, fornitore_id=6,
            codice_fornitore="00141", descrizione="Buste ambra N.U. PE/LD cm 90x120h 18kg",
            data_documento=date(2026, 11, 7), quantita=Decimal("30"), netto_unitario=Decimal("1.5667"),
        )]
        listini = {(6, SACCHI_SKU): [listino(1731, "25.80", None, date(2026, 10, 27), alias_id=1731)]}
        [line] = vl.build_waste_lines(rows, {576: sacchi}, AliasIndex([]), listini, {6: "EUROCARTA SRLS"})
        self.assertIsNone(line.prezzo_listino)
        self.assertEqual(line.fornitore, "EUROCARTA SRLS")
        self.assertEqual(vl.line_reference(line, Decimal("1.5"))[1], "minimo")

    def test_build_lines_uses_listino_valid_at_row_date(self):
        rows = [SimpleNamespace(
            riga_id=n, sku_interno=MINI_PANINO_SKU, unita="CT", unita_misura="CT", product_id=1, fornitore_id=9,
            codice_fornitore="PPANVE", descrizione=self.ALIAS.raw_description, data_documento=day,
            quantita=Decimal("2"), netto_unitario=Decimal("26.98"),
        ) for n, day in ((1, date(2026, 10, 20)), (2, date(2026, 11, 3)))]
        listini = {(9, MINI_PANINO_SKU): [listino(2, "0.25", None, date(2026, 10, 27), alias_id=2)]}
        before, after = vl.build_waste_lines(rows, {1: self.MINI_PANINO}, AliasIndex([self.ALIAS]), listini, {})
        self.assertIsNone(before.prezzo_listino)
        self.assertEqual(after.prezzo_listino, Decimal("25.00"))


class QueryRulesTest(unittest.TestCase):
    def test_paid_lines_rules(self):
        text = sql(vl.paid_purchase_lines(ADMIN))
        self.assertIn("WHERE (fatture.tenant_id", text)
        self.assertIn("AND (fatture.tipo_documento NOT IN", text)  # no TD04/TD08
        literal = str(vl.paid_purchase_lines(ADMIN).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        self.assertIn("NOT IN ('TD04', 'TD08')", literal)
        self.assertIn("skus_esclusi", text)
        self.assertIn("righe_escluse_statistiche", text)
        self.assertIn("tenant_id", text)
        self.assertIn("is_omaggio", text)
        # The overwritten column is never read: net = pu x (1 - discount).
        self.assertNotIn("prezzo_netto_normalizzato", text)

    def test_leaderboard_minimum_per_item_and_unit_with_tie_break(self):
        text = sql(vl.efficiency_leaderboard_select(ADMIN))
        self.assertIn("PARTITION BY righe.sku_interno, righe.unita", text)
        self.assertIn("ORDER BY score DESC, totali DESC, acquisti.location_id ASC NULLS LAST", text)
        self.assertIn("skus_esclusi", text)
        self.assertNotIn("prezzo_netto_normalizzato", text)

    def test_period_start_is_returned_as_date(self):
        from datetime import datetime, timezone
        self.assertEqual(vl.check_start_date(datetime(2026, 11, 6, 18, 0, tzinfo=timezone.utc)), "2026-11-06")
        self.assertIsNone(vl.check_start_date(None))


if __name__ == "__main__":
    unittest.main()
